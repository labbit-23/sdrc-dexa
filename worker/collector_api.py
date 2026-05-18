"""
FastAPI sidecar — HTTP wrapper around the Python worker functions.
Runs on localhost:7437, managed by PM2 alongside the Next.js app.

The Next.js /bmd/fetch page calls these endpoints via /api/collector/* proxy.
"""

import json
import logging
import queue
import threading
from datetime import datetime
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
    upload_patient_trend,
)
from sync_supabase import check_scan_exists, get_uploaded_mrns

log = logging.getLogger(__name__)

app = FastAPI(title='SDRC Collector API', version='1.0')
app.add_middleware(
    CORSMiddleware,
    allow_origins=['http://localhost:3000', 'http://localhost:3010',
                   'http://127.0.0.1:3000', 'http://127.0.0.1:3010'],
    allow_methods=['GET', 'POST'],
    allow_headers=['*'],
)


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
def recent(hours: int = 48):
    """Recent patients (last N hours) + XPS status + Supabase duplicate flag."""
    try:
        patients = get_recent_patients(hours=hours)
    except Exception as e:
        _mdb_error(e)
    out = []
    for info in patients:
        pid      = info['patient'].get('patient_id', '')
        sd       = info.get('scan_date')
        date_str = sd.strftime('%Y-%m-%d') if sd else ''
        exists   = bool(date_str and check_scan_exists(pid, date_str))
        out.append({**_jsonify(info), 'exists_in_db': exists})
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
    return _jsonify(patients)


@app.get('/db-mrns')
def db_mrns():
    """Return all patient MRNs already uploaded to Supabase. Single batch call."""
    try:
        return {'mrns': list(get_uploaded_mrns())}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get('/xps/{patient_id}')
def xps_for_patient(patient_id: str):
    """Check which XPS files exist for a given patient in the watch directory."""
    files = find_xps_for_patient(patient_id)
    return {'patient_id': patient_id, 'xps_files': files, 'found': len(files) > 0}


class TrendBody(BaseModel):
    scan_type: str  # 'osteo_trend' | 'total_body_trend'


class UploadBody(BaseModel):
    xps_paths: list[str] = []


# ── Archive MDB endpoints ─────────────────────────────────────────────────────

def _archive_path() -> str:
    p = (config.ARCHIVE_MDB_PATH or '').strip()
    return p


@app.get('/archive/status')
def archive_status():
    """Check whether the archive MDB is configured and readable."""
    path = _archive_path()
    if not path:
        return {'available': False, 'reason': 'ARCHIVE_MDB_PATH not set in .env'}
    from pathlib import Path as _Path
    if not _Path(path).exists():
        return {'available': False, 'path': path, 'reason': 'File not found at configured path'}
    return {'available': True, 'path': path}


@app.get('/archive/all')
def archive_all(q: Optional[str] = None, max_count: int = 500):
    """All patients from the archive MDB, optional name/MRN filter."""
    path = _archive_path()
    if not path:
        raise HTTPException(status_code=503, detail='ARCHIVE_MDB_PATH not configured')
    try:
        patients = get_all_patients_from_path(path, max_count=max_count)
    except Exception as e:
        raise HTTPException(status_code=503, detail={'error': str(e), 'bmd_offline': False})
    if q:
        ql = q.lower()
        patients = [
            p for p in patients
            if ql in (p['patient'].get('patient_id') or '').lower()
            or ql in (p['patient'].get('name') or '').lower()
        ]
    return _jsonify(patients)


@app.post('/archive/trend/{patient_id}')
def archive_trend(patient_id: str, body: TrendBody):
    """Upload a trend record from the archive MDB (no XPS)."""
    path = _archive_path()
    if not path:
        raise HTTPException(status_code=503, detail='ARCHIVE_MDB_PATH not configured')
    msgs: list[str] = []
    try:
        result = upload_patient_trend(
            patient_id, body.scan_type,
            progress_cb=lambda m: msgs.append(m),
            mdb_path=path,
        )
        return {'ok': True, 'messages': msgs, 'result': _jsonify(result)}
    except Exception as e:
        log.exception('archive trend upload failed: %s', e)
        raise HTTPException(status_code=500, detail=str(e))


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
            from parse_xps import detect_xps_type
            tb_types = {'totalbody_bone', 'totalbody_composition', 'totalbody_narrative'}
            types = [detect_xps_type(p) for p in xps]
            is_totalbody = any(t in tb_types for t in types)

            if is_totalbody:
                from collect_totalbody import upload_totalbody_scan
                xps_map: dict[str, str] = {}
                for p, t in zip(xps, types):
                    if t == 'totalbody_bone' and 'bone' not in xps_map:
                        xps_map['bone'] = p
                    elif t in ('totalbody_composition', 'totalbody_narrative') and 'composition' not in xps_map:
                        xps_map['composition'] = p
                result = upload_totalbody_scan(patient_id, xps_map, progress_cb=_cb)
            else:
                from collect_osteo import upload_osteo_scan, _classify_xps
                xps_map = {}
                for p in xps:
                    label = _classify_xps(p)
                    if label == 'combined':
                        xps_map = {'spine': p, 'left_femur': p, 'right_femur': p}
                        break
                    elif label in ('spine', 'left_femur', 'right_femur'):
                        xps_map[label] = p
                result = upload_osteo_scan(patient_id, xps_map, progress_cb=_cb)

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
