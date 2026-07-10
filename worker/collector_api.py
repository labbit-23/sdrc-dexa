"""
FastAPI sidecar — HTTP wrapper around the Python worker functions.
Runs on localhost:7437, managed by PM2 alongside the Next.js app.

The Next.js /bmd/fetch page calls these endpoints via /api/collector/* proxy.
"""

import json
import logging
import queue
import threading
from datetime import datetime, timedelta
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import config
from collect import (
    find_xps_for_patient,
    get_all_patients,
    get_all_patients_from_path,
    get_recent_patients,
    upload_patient_raw,
)
from sync_supabase import (
    check_scan_exists,
    get_uploaded_mrns,
    get_uploaded_mrns_with_type,
    get_recent_scans_by_source,
    upload_patient_trend,
)

log = logging.getLogger(__name__)

app = FastAPI(title='SDRC Collector API', version='1.0')
app.add_middleware(
    CORSMiddleware,
    allow_origins=['http://localhost:3000', 'http://localhost:3010',
                   'http://127.0.0.1:3000', 'http://127.0.0.1:3010'],
    allow_methods=['GET', 'POST'],
    allow_headers=['*'],
)

# Cache parsed MDB files to avoid reloading on every request
_mdb_cache = {}

def _get_cached_parser(mdb_path: str):
    """Get or create a cached MdbParser for the given MDB path."""
    if mdb_path not in _mdb_cache:
        from parse_mdb import MdbParser
        _mdb_cache[mdb_path] = MdbParser(mdb_path)
    return _mdb_cache[mdb_path]

def _get_all_patients_cached(mdb_path: str, max_count: int = 500) -> list[dict]:
    """Like get_all_patients_from_path but uses cached MdbParser."""
    parser = _get_cached_parser(mdb_path)
    results = []
    seen_pids = set()

    for exam in sorted(parser._exams,
                       key=lambda e: e.get('_acq_dt') or datetime.min,
                       reverse=True):
        pat_handle = exam.get('pat_handle', '')
        pat_row = parser._patients.get(pat_handle)
        if not pat_row:
            continue
        pid = pat_row.get('patient_id', '').strip()
        if not pid or pid in seen_pids:
            continue
        seen_pids.add(pid)

        patient = parser._parse_patient(pat_row)
        all_handles = [ph for ph, row in parser._patients.items()
                       if row.get('patient_id', '').strip() == pid]
        all_sessions = []
        for ph in all_handles:
            all_sessions.extend(parser.get_scan_sessions(ph))
        all_sessions.sort(
            key=lambda s: s.get('scan_date') or datetime.min, reverse=True)
        session = all_sessions[0] if all_sessions else {}
        results.append({
            'patient':   patient,
            'session':   session,
            'sessions':  all_sessions,
            'scan_date': exam.get('_acq_dt'),
        })
        if len(results) >= max_count:
            break

    return results


# ── Serialisation ─────────────────────────────────────────────────────────────

def _ser(v):
    if isinstance(v, datetime):
        return v.isoformat()
    return v

def _jsonify(obj):
    if isinstance(obj, dict):
        return {k: _jsonify(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_jsonify(i) for i in obj]
    return _ser(obj)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get('/status')
def status():
    return {
        'ok':      True,
        'mdb':     config.MDB_PATH,
        'xps_dir': config.XPS_WATCH_DIR,
    }


def _derive_scan_components(session_or_sessions) -> dict:
    """
    Derive human-readable scan component info from one or more MDB session dicts.

    Accepts either a single session dict (legacy) or a list of sessions.
    Aggregates across all sessions so a patient with both osteo and total-body
    scans shows all components, not just the most recent one.

    Returns:
      mdb_scan_type   – 'total_body' if any session is total_body, else 'osteo'
      scan_components – sorted list, e.g. ['AP Spine', 'Left Femur', 'Left Forearm', 'Total Body']
      has_spine       – bool
      has_left_femur  – bool
      has_right_femur – bool
      has_left_forearm – bool
      has_right_forearm – bool
      has_total_body  – bool
      has_osteo       – bool
    """
    sessions = (
        session_or_sessions if isinstance(session_or_sessions, list)
        else [session_or_sessions] if session_or_sessions else []
    )

    has_total_body = any(s.get('mdb_scan_type') == 'total_body' for s in sessions)
    has_osteo      = any(s.get('mdb_scan_type') == 'osteo'       for s in sessions)
    has_spine      = any(bool(s.get('spine'))       for s in sessions)
    has_left       = any(bool(s.get('left_femur'))  for s in sessions)
    has_right      = any(bool(s.get('right_femur')) for s in sessions)
    has_left_fa    = any(bool(s.get('left_forearm'))  for s in sessions)
    has_right_fa   = any(bool(s.get('right_forearm')) for s in sessions)

    components = []
    if has_total_body:              components.append('Total Body')
    if has_spine:                   components.append('AP Spine')
    if has_left:                    components.append('Left Femur')
    if has_right:                   components.append('Right Femur')
    if has_left_fa:                 components.append('Left Forearm')
    if has_right_fa:                components.append('Right Forearm')

    # Primary routing type: total_body takes precedence when both exist
    mdb_scan_type = 'total_body' if has_total_body else 'osteo'

    return {
        'mdb_scan_type':    mdb_scan_type,
        'scan_components':  components,
        'has_spine':        has_spine,
        'has_left_femur':   has_left,
        'has_right_femur':  has_right,
        'has_left_forearm':  has_left_fa,
        'has_right_forearm': has_right_fa,
        'has_total_body':   has_total_body,
        'has_osteo':        has_osteo,
    }


def _mdb_error(e: Exception):
    msg = str(e)
    # CIFS/network mount failures surface as file-not-found or permission errors
    bmd_offline = any(k in msg.lower() for k in (
        'no such file', 'permission denied', 'transport endpoint',
        'stale file handle', 'connection', 'network', 'mdb', 'odbc',
    ))
    detail = (
        'Cannot reach BMD PC — check that it is turned on and connected to the network.'
        if bmd_offline else msg
    )
    raise HTTPException(status_code=503, detail={'error': detail, 'bmd_offline': bmd_offline})


@app.get('/recent')
def recent(
    hours:     int = 48,
    date_from: Optional[str] = None,
    date_to:   Optional[str] = None,
):
    """
    Recent patients + scans from MDB (available to upload), with Supabase supplement info.

    Pass date_from / date_to (ISO date strings, e.g. '2026-05-01') to query a
    specific date range instead of the rolling `hours` window.

    Returns array of scan records from MDB, each with:
    - patient info (name, MRN, etc.)
    - scan_date, scan_type, XPS filename
    - exists_in_db: whether this scan date is already uploaded to Supabase
    """
    from_dt: Optional[datetime] = None
    to_dt:   Optional[datetime] = None
    try:
        if date_from:
            from_dt = datetime.fromisoformat(date_from)
        if date_to:
            # end-of-day so the whole target date is included
            to_dt = datetime.fromisoformat(date_to).replace(hour=23, minute=59, second=59)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f'Invalid date format: {e}')

    try:
        patients = get_recent_patients(date_from=from_dt, date_to=to_dt, hours=hours)
    except Exception as e:
        _mdb_error(e)

    # Return ALL scans per patient (not deduplicated), so user can upload each separately
    out = []
    for info in patients:
        pid       = info['patient'].get('patient_id', '')
        sd        = info.get('scan_date')
        scan_date_iso = sd.isoformat() if sd else ''
        # Extract scan_type (mdb_scan_type) from sessions on this date
        sessions  = info.get('sessions') or [info.get('session', {})]
        actual_scan_type = sessions[0].get('mdb_scan_type') if sessions else None
        exists    = bool(scan_date_iso and check_scan_exists(pid, scan_date_iso, actual_scan_type))
        components = _derive_scan_components(sessions)
        out.append({**_jsonify(info), 'scan_type': actual_scan_type, 'exists_in_db': exists, **components})
    return out


@app.get('/all')
def all_patients(q: Optional[str] = None, max_count: int = 200):
    """Full MDB patient list, optional MRN/name filter."""
    try:
        patients = get_all_patients(max_count=max_count)
    except Exception as e:
        _mdb_error(e)
    if q:
        ql = q.lower()
        patients = [
            p for p in patients
            if ql in (p['patient'].get('patient_id') or '').lower()
            or ql in (p['patient'].get('name') or '').lower()
        ]
    return _jsonify([
        {**p, **_derive_scan_components(p.get('sessions') or [p.get('session', {})])}
        for p in patients
    ])


@app.get('/db-mrns')
def db_mrns():
    """Return all uploaded patients as {by_mrn: {patient_id: scan_type}}."""
    try:
        return {'by_mrn': get_uploaded_mrns_with_type()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get('/xps/{patient_id}')
def xps_for_patient(patient_id: str):
    """Check which XPS files exist for a given patient, with scan-type labels."""
    from pathlib import Path as _Path
    from collect_osteo import _classify_xps

    files = find_xps_for_patient(patient_id)
    typed = []
    for f in files:
        try:
            label = _classify_xps(f)
            # Map classification to UI type: forearm/spine/femur → osteo, total_body → total_body
            if label in ('left_forearm', 'right_forearm', 'spine', 'left_femur', 'right_femur', 'combined', 'dual_femur'):
                xtype = 'osteo'
            else:
                xtype = 'unknown'
        except Exception:
            xtype = 'unknown'
        typed.append({'path': f, 'name': _Path(f).name, 'type': xtype})

    return {'patient_id': patient_id, 'xps_files': files, 'xps_typed': typed, 'found': len(files) > 0}


class TrendBody(BaseModel):
    scan_type: str  # 'osteo_trend' | 'total_body_trend'


class UploadBody(BaseModel):
    xps_paths:          list[str] = []
    scan_type_override: Optional[str] = None   # 'osteo' | 'total_body'
    scan_date:          Optional[str] = None   # ISO date of selected scan (YYYY-MM-DD or full ISO)


# ── Archive MDB endpoints ─────────────────────────────────────────────────────

def _archive_paths() -> list[dict]:
    """Return list of {path, label} dicts for all configured archive MDBs."""
    from pathlib import Path as _Path
    return [
        {'path': p, 'label': _Path(p).stem}
        for p in config.ARCHIVE_MDB_PATHS
    ]


@app.get('/archive/status')
def archive_status():
    """Check whether any archive MDB is configured and readable."""
    from pathlib import Path as _Path
    archives = _archive_paths()
    if not archives:
        return {'available': False, 'reason': 'ARCHIVE_MDB_PATH not set in .env', 'archives': []}
    out = []
    for a in archives:
        exists = _Path(a['path']).exists()
        out.append({**a, 'available': exists,
                    'reason': None if exists else 'File not found at configured path'})
    return {'available': any(a['available'] for a in out), 'archives': out}


@app.get('/archive/all')
def archive_all(q: Optional[str] = None, max_count: int = 500):
    """All patients from all archive MDBs, tagged with all matching archives."""
    from pathlib import Path as _Path
    archives = _archive_paths()
    if not archives:
        raise HTTPException(status_code=503, detail='ARCHIVE_MDB_PATH not configured')
    by_pid: dict[str, dict] = {}  # patient_id → {patient, sessions, archive_labels}
    seen_per_archive: dict[str, int] = {}  # archive_label → count for max_count per archive

    for a in archives:
        if not _Path(a['path']).exists():
            log.warning('archive_all: skipping missing %s', a['path'])
            continue
        try:
            patients = _get_all_patients_cached(a['path'], max_count=max_count)
        except Exception as e:
            log.warning('archive_all: error reading %s: %s', a['label'], e)
            continue
        for p in patients:
            pid = (p.get('patient') or {}).get('patient_id', '')
            if not pid:
                continue
            # Track which archives have this patient (de-dupe but keep archive list)
            if pid not in by_pid:
                by_pid[pid] = {**p, 'archive_labels': []}
            if a['label'] not in by_pid[pid]['archive_labels']:
                by_pid[pid]['archive_labels'].append(a['label'])

    # Convert to list with scan type info from first archive
    merged = []
    for pid, p in by_pid.items():
        sessions = p.get('sessions', [])
        has_total_body = any(s.get('mdb_scan_type') == 'total_body' for s in sessions)
        has_osteo = any(s.get('mdb_scan_type') == 'osteo' for s in sessions)
        mdb_scan_type = 'total_body' if has_total_body else 'osteo' if has_osteo else None
        # Use first archive label as default; UI can choose from archive_labels
        archive_label = p['archive_labels'][0] if p['archive_labels'] else ''
        merged.append({**p, 'archive_label': archive_label, 'archive_labels': p['archive_labels'], 'has_total_body': has_total_body, 'has_osteo': has_osteo, 'mdb_scan_type': mdb_scan_type})

    if q:
        ql = q.lower()
        merged = [
            p for p in merged
            if ql in ((p['patient'].get('patient_id') or '').lower())
            or ql in ((p['patient'].get('name') or '').lower())
        ]
    return _jsonify(merged)


@app.post('/archive/trend/{patient_id}')
def archive_trend(patient_id: str, body: TrendBody, mdb: Optional[str] = None, date: Optional[str] = None):
    """Upload a trend record from an archive MDB (no XPS). Pass ?mdb=label to target a specific archive."""
    from pathlib import Path as _Path

    archives = _archive_paths()
    if not archives:
        raise HTTPException(status_code=503, detail='ARCHIVE_MDB_PATH not configured')
    if mdb:
        candidates = [a for a in archives if a['label'] == mdb]
        if not candidates:
            raise HTTPException(status_code=404, detail=f'Archive "{mdb}" not found')
    else:
        candidates = [a for a in archives if _Path(a['path']).exists()]

    last_error: Exception | None = None
    for a in candidates:
        msgs: list[str] = []
        try:
            # Use the same upload functions as regular scans, just for trends
            if body.scan_type == 'total_body_trend':
                from collect_totalbody import upload_totalbody_trend_scan
                result = upload_totalbody_trend_scan(
                    patient_id, a['path'],
                    progress_cb=lambda m: msgs.append(m),
                )
            elif body.scan_type == 'osteo_trend':
                from collect_osteo import upload_osteo_trend_scan
                result = upload_osteo_trend_scan(
                    patient_id, a['path'],
                    progress_cb=lambda m: msgs.append(m),
                    scan_date=date,
                )
            else:
                raise ValueError(f'Invalid trend scan_type: {body.scan_type}')

            return {'ok': True, 'messages': msgs, 'result': _jsonify(result), 'archive': a['label']}
        except Exception as e:
            log.warning('archive trend: %s not found in %s: %s', patient_id, a['label'], e)
            last_error = e
    log.exception('archive trend upload failed for %s: %s', patient_id, last_error)
    raise HTTPException(status_code=500, detail=str(last_error))


@app.post('/upload/{patient_id}')
def upload(patient_id: str, body: UploadBody):
    """
    Upload MDB snapshot + XPS images for one patient.
    Returns a Server-Sent Events stream of progress messages.
    Each event: data: {"msg": "..."} or {"done": true} or {"error": "..."}
    """
    xps = body.xps_paths or find_xps_for_patient(patient_id)

    # Run the blocking upload in a thread; pipe progress via a queue
    q: queue.Queue = queue.Queue()
    _DONE = object()

    def _run():
        def _cb(msg):
            q.put({'msg': msg})
        try:
            # ── Determine scan type ───────────────────────────────────────────
            # Explicit override (from UI button) takes absolute precedence.
            # Otherwise fall back to MDB — the single source of truth.
            if body.scan_type_override in ('osteo', 'total_body'):
                mdb_scan_type = body.scan_type_override
                log.info('upload %s: scan type override = %s', patient_id, mdb_scan_type)
                _cb(f'Scan type: {mdb_scan_type} (explicit)')
            else:
                from parse_mdb import MdbParser
                parser = MdbParser(config.MDB_PATH)
                pat_handles = [
                    ph for ph, row in parser._patients.items()
                    if row.get('patient_id', '').strip() == patient_id
                ]
                mdb_scan_type = 'osteo'  # safe default
                if pat_handles:
                    session = parser.get_latest_session(pat_handles[0])
                    if session:
                        mdb_scan_type = session.get('mdb_scan_type', 'osteo')
                log.info('upload %s: MDB scan type = %s', patient_id, mdb_scan_type)
                _cb(f'MDB scan type: {mdb_scan_type}')

            is_totalbody = (mdb_scan_type == 'total_body')

            if is_totalbody:
                # Within total-body, XPS sub-type (bone vs composition) is
                # legitimately XPS-only information — MDB doesn't distinguish.
                from parse_xps import detect_xps_type
                from collect_totalbody import upload_totalbody_scan
                xps_map: dict[str, str] = {}
                for p in xps:
                    t = detect_xps_type(p)
                    if t == 'totalbody_bone' and 'bone' not in xps_map:
                        xps_map['bone'] = p
                    elif t in ('totalbody_composition', 'totalbody_narrative') and 'composition' not in xps_map:
                        xps_map['composition'] = p
                result = upload_totalbody_scan(patient_id, xps_map, progress_cb=_cb)
            else:
                # Osteo: _classify_xps maps XPS files to image slots
                # (spine / left_femur / right_femur / left_forearm / right_forearm / combined / dual_femur).
                # The osteo vs total-body routing was already decided by MDB above.
                from collect_osteo import upload_osteo_scan, _classify_xps
                xps_map = {}
                for p in xps:
                    label = _classify_xps(p)
                    if label == 'combined':
                        xps_map = {'spine': p, 'left_femur': p, 'right_femur': p}
                        break
                    elif label == 'dual_femur':
                        xps_map = {'left_femur': p, 'right_femur': p}
                        break
                    elif label in ('spine', 'left_femur', 'right_femur', 'left_forearm', 'right_forearm'):
                        xps_map[label] = p
                result = upload_osteo_scan(patient_id, xps_map, progress_cb=_cb, scan_date=body.scan_date)

            q.put({'done': True, 'result': _jsonify(result)})
        except Exception as e:
            log.exception('upload failed: %s', e)
            q.put({'error': str(e)})
        finally:
            q.put(_DONE)

    threading.Thread(target=_run, daemon=True).start()

    def _stream():
        while True:
            item = q.get()
            if item is _DONE:
                break
            yield f'data: {json.dumps(item)}\n\n'

    return StreamingResponse(
        _stream(),
        media_type='text/event-stream',
        headers={
            'Cache-Control':    'no-cache',
            'X-Accel-Buffering': 'no',
        },
    )


@app.post('/trend/{patient_id}')
def trend(patient_id: str, body: TrendBody):
    """Upload MDB-only snapshot as trend data (no XPS required)."""
    msgs: list[str] = []
    try:
        result = upload_patient_trend(
            patient_id, body.scan_type,
            progress_cb=lambda m: msgs.append(m),
        )
        return {'ok': True, 'messages': msgs, 'result': _jsonify(result)}
    except Exception as e:
        log.exception('trend upload failed: %s', e)
        raise HTTPException(status_code=500, detail=str(e))


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s: %(message)s',
    )
    uvicorn.run(app, host='127.0.0.1', port=7437, log_level='info')
