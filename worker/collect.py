"""
Raw data collector — Windows side only.

Reads the MDB for recent patients, finds their XPS files,
extracts + colorizes scan images from XPS, and uploads everything to
Supabase Storage so the Next.js Labit BMD screen can render PDFs without
needing to understand the XPS format.

Storage layout per patient upload:
  raw/{patient_id}/{timestamp}/
    mdb_snapshot.json      — all MDB rows for this patient (JSON)
    img_fat_lean.png       — composition silhouette, fat=pink / lean=cyan
    img_fat_gradient.png   — composition silhouette, fat heat-map
    img_bone.png           — bone scan silhouette
    Full_body.xps          — raw XPS (bone scan), kept for reference
    Full_body-1.xps        — raw XPS (composition), kept for reference
    …
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import config
from parse_mdb import MdbParser

log = logging.getLogger(__name__)


# ── Patient + XPS discovery ───────────────────────────────────────────────────

def get_recent_patients(
    date_from: Optional[datetime] = None,
    date_to:   Optional[datetime] = None,
    hours:     int = 48,
) -> list[dict]:
    """
    Return patients who had a scan within the given date range, newest first.

    If date_from/date_to are provided they take precedence over `hours`.
    date_to defaults to end-of-day today when only date_from is given.
    Caps at 50 results to keep MDB reads small.
    """
    parser = MdbParser(config.MDB_PATH)

    if date_from is not None:
        lo = date_from
        hi = date_to if date_to is not None else datetime.now().replace(
            hour=23, minute=59, second=59)
    else:
        hi = datetime.now()
        lo = hi - timedelta(hours=hours)

    results = []
    seen_pids = set()

    for exam in sorted(parser._exams,
                       key=lambda e: e.get('_acq_dt') or datetime.min,
                       reverse=True):
        acq = exam.get('_acq_dt')
        if not acq:
            continue
        if acq > hi:
            continue
        if acq < lo:
            break  # sorted newest-first; nothing older will match

        pat_handle = exam.get('pat_handle', '')
        pat_row = parser._patients.get(pat_handle)
        if not pat_row:
            continue
        pid = pat_row.get('patient_id', '').strip()
        if not pid or pid in seen_pids:
            continue
        seen_pids.add(pid)

        patient  = parser._parse_patient(pat_row)

        # Gather sessions from ALL pat_handles that share this patient_id.
        # The GE Lunar scanner sometimes creates separate patient records for
        # the same person (one for osteo, one for total body), so a single
        # pat_handle may not have all sessions.
        all_pat_handles = [
            ph for ph, row in parser._patients.items()
            if row.get('patient_id', '').strip() == pid
        ]
        all_sessions = []
        for ph in all_pat_handles:
            all_sessions.extend(parser.get_scan_sessions(ph))
        all_sessions.sort(
            key=lambda s: s.get('scan_date') or datetime.min, reverse=True
        )
        session  = all_sessions[0] if all_sessions else {}

        xps_found = find_xps_for_patient(pid, acq)
        results.append({
            'patient':     patient,
            'session':     session,    # most-recent session (for compat)
            'sessions':    all_sessions,  # all sessions (for component display)
            'scan_date':   acq,
            'xps_files':   xps_found,
            'xps_missing': len(xps_found) == 0,
        })

        if len(results) >= 50:
            break

    return results


def find_xps_for_patient(patient_id: str,
                         scan_date: Optional[datetime] = None) -> list[str]:
    """
    Find XPS files in XPS_WATCH_DIR that match this patient_id.
    Returns list of absolute path strings (may be empty).
    """
    watch = Path(config.XPS_WATCH_DIR)
    if not watch.exists():
        return []

    # Match any XPS whose stem starts with patient_id
    matches = [str(f.resolve())
               for f in watch.glob('*.xps')
               if f.stem.split('-')[0].strip() == patient_id]

    # Also try fuzzy: patient_id anywhere in the name
    if not matches:
        matches = [str(f.resolve())
                   for f in watch.glob('*.xps')
                   if patient_id in f.stem]

    # If still none, try the most recent XPS from today
    if not matches and scan_date and scan_date.date() == datetime.now().date():
        all_xps = sorted(watch.glob('*.xps'), key=lambda f: f.stat().st_mtime)
        if all_xps:
            matches = [str(all_xps[-1].resolve())]

    return matches


# ── MDB snapshot for one patient ──────────────────────────────────────────────

def mdb_snapshot(patient_id: str, mdb_path: str = '') -> dict:
    """
    Extract a JSON-serialisable snapshot of MDB data for one patient.
    Includes all patient rows, all exams, all composition and densitometry rows.
    Pass mdb_path to read from an alternative MDB (e.g. archive).
    """
    parser = MdbParser(mdb_path or config.MDB_PATH)

    def _ser(v):
        if isinstance(v, datetime):
            return v.isoformat()
        return v

    pat_handles = [
        ph for ph, row in parser._patients.items()
        if row.get('patient_id', '').strip() == patient_id
    ]

    # Use _parse_patient() so fields like dob are properly converted
    # (raw rows have birth_time as Excel serial, not a usable date string)
    def _ser_patient(parsed: dict) -> dict:
        out = {}
        for k, v in parsed.items():
            if hasattr(v, 'isoformat'):   # date or datetime
                out[k] = v.isoformat()
            else:
                out[k] = _ser(v)
        return out

    patients_out = {ph: _ser_patient(parser._parse_patient(parser._patients[ph]))
                    for ph in pat_handles}

    exams_out = [
        {k: _ser(v) for k, v in e.items()}
        for e in parser._exams
        if e.get('pat_handle') in pat_handles
    ]

    img_handles = {e['img_handle'] for e in exams_out if e.get('img_handle')}

    comp_out = {
        h: [{k: _ser(v) for k, v in row.items()} for row in rows]
        for h, rows in parser._composition.items()
        if h in img_handles
    }
    dens_out = {
        h: [{k: _ser(v) for k, v in row.items()} for row in rows]
        for h, rows in parser._densitometry.items()
        if h in img_handles
    }

    return {
        'patient_id':    patient_id,
        'snapshot_ts':   datetime.utcnow().isoformat(),
        'patients':      patients_out,
        'exams':         exams_out,
        'composition':   comp_out,
        'densitometry':  dens_out,
    }


# ── All-patients lookup (for Link Older Study) ────────────────────────────────

def get_all_patients_from_path(mdb_path: str, max_count: int = 500) -> list[dict]:
    """
    Same as get_all_patients() but reads from an explicit MDB path.
    Used for the archive MDB feature.
    """
    parser = MdbParser(mdb_path)
    results = []
    seen_pids: set[str] = set()

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

        patient  = parser._parse_patient(pat_row)
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


def get_all_patients(max_count: int = 200) -> list[dict]:
    """
    Return up to max_count patients from MDB, newest scan first.
    No XPS search — used for the Link Older Study dialog.
    """
    parser = MdbParser(config.MDB_PATH)
    results = []
    seen_pids: set[str] = set()

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

        patient  = parser._parse_patient(pat_row)
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


def upload_patient_trend(patient_id: str, scan_type: str,
                         progress_cb=None, mdb_path: str = '') -> dict:
    """
    Upload MDB-only snapshot for a patient as trend data (no XPS / images).
    scan_type: 'osteo_trend' or 'total_body_trend'
    Pass mdb_path to read from an alternative MDB (e.g. archive).
    """
    from sync_supabase import upload_trend_scan
    notify = progress_cb or (lambda msg: log.info(msg))

    notify(f'Reading MDB for {patient_id}…')
    snapshot   = mdb_snapshot(patient_id, mdb_path=mdb_path)
    snap_bytes = json.dumps(snapshot, indent=2).encode()

    notify('Uploading trend data to Supabase…')
    result = upload_trend_scan(patient_id, snap_bytes, scan_type, notify)
    notify('Done — trend data linked.')
    return result


# ── Image extraction from XPS ─────────────────────────────────────────────────

def _extract_png_images(xps_paths: list[str],
                        notify) -> dict[str, bytes]:
    """
    Extract and colorize scan images from XPS files.
    Returns {filename: png_bytes}.  Never raises — logs warnings on failure.
    """
    import io
    from parse_xps import detect_xps_type

    pngs: dict[str, bytes] = {}
    bone_xps = comp_xps = None

    for path in xps_paths:
        try:
            xtype = detect_xps_type(path)
        except Exception:
            continue
        if xtype == 'totalbody_bone' and bone_xps is None:
            bone_xps = path
        elif xtype == 'totalbody_composition' and comp_xps is None:
            comp_xps = path

    if bone_xps or comp_xps:
        notify("Extracting totalbody scan images…")
        try:
            from parse_xps_totalbody import (
                extract_totalbody_images, colorize_dexa_silhouette,
            )
            imgs = extract_totalbody_images(bone_xps, comp_xps)

            # composition silhouette → fat_lean + fat_gradient
            raw_comp = imgs.get('bmd_chart')
            if raw_comp:
                for mode, fname in [
                    ('fat_lean',     'img_fat_lean.png'),
                    ('fat_gradient', 'img_fat_gradient.png'),
                ]:
                    try:
                        colored = colorize_dexa_silhouette(raw_comp, mode=mode)
                        buf = io.BytesIO()
                        colored.save(buf, 'PNG', optimize=True)
                        pngs[fname] = buf.getvalue()
                        notify(f"  {fname} ({len(pngs[fname])//1024} KB)")
                    except Exception as e:
                        log.warning("colorize %s failed: %s", mode, e)

            # bone silhouette
            raw_bone = imgs.get('body_silhouette')
            if raw_bone:
                try:
                    colored = colorize_dexa_silhouette(raw_bone, mode='bone')
                    buf = io.BytesIO()
                    colored.save(buf, 'PNG', optimize=True)
                    pngs['img_bone.png'] = buf.getvalue()
                    notify(f"  img_bone.png ({len(pngs['img_bone.png'])//1024} KB)")
                except Exception as e:
                    log.warning("colorize bone failed: %s", e)

            # composite: fat/lean body + bone structure overlay
            if 'img_fat_lean.png' in pngs and 'img_bone.png' in pngs:
                try:
                    import numpy as np
                    from PIL import Image as _Image
                    fl = _Image.open(io.BytesIO(pngs['img_fat_lean.png'])).convert('RGB')
                    b  = _Image.open(io.BytesIO(pngs['img_bone.png'])).convert('RGB')
                    b_r = b.resize(fl.size, _Image.LANCZOS)
                    fl_arr = np.array(fl).astype(float) / 255.0
                    b_arr  = np.array(b_r).astype(float) / 255.0
                    mask   = np.clip(b_arr.mean(axis=2, keepdims=True) * 1.4, 0, 1)
                    bone_color = np.array([[[0.9, 1.0, 0.9]]])
                    comp = np.clip(fl_arr * (1 - 0.55 * mask) + bone_color * (0.55 * mask), 0, 1)
                    out = _Image.fromarray((comp * 255).astype(np.uint8))
                    buf = io.BytesIO()
                    out.save(buf, 'PNG', optimize=True)
                    pngs['img_composite.png'] = buf.getvalue()
                    notify(f"  img_composite.png ({len(pngs['img_composite.png'])//1024} KB)")
                except Exception as e:
                    log.warning("composite generation failed: %s", e)

        except Exception as e:
            log.warning("extract_totalbody_images failed: %s", e)
            notify(f"  Warning: image extraction failed ({e})")

    return pngs


# ── Upload ────────────────────────────────────────────────────────────────────

def upload_patient_raw(patient_id: str, xps_paths: list[str],
                       progress_cb=None) -> dict:
    """
    Full raw upload for one patient:
      1. MDB snapshot → JSON
      2. XPS → colorized PNG images (fat_lean, fat_gradient, bone)
      3. Raw XPS bytes (for reference)
    All land in Supabase Storage under raw/{patient_id}/{timestamp}/

    progress_cb(message: str) is called with status updates.
    Returns the result dict from upload_raw_files.
    """
    from sync_supabase import upload_raw_files
    notify = progress_cb or (lambda msg: log.info(msg))

    # 1. MDB snapshot
    notify(f"Reading MDB for patient {patient_id}…")
    snapshot  = mdb_snapshot(patient_id)
    snap_json = json.dumps(snapshot, indent=2).encode()

    # 2. Colorized PNG images
    png_images = _extract_png_images(xps_paths, notify)
    if not png_images:
        notify("  Note: no images extracted (spine/femur scan or XPS unreadable)")

    # 3. Raw XPS bytes
    xps_data: dict[str, bytes] = {}
    for path in xps_paths:
        p = Path(path)
        notify(f"Reading {p.name}…")
        xps_data[p.name] = p.read_bytes()

    # 4. Upload everything
    notify("Uploading to Supabase Storage…")
    result = upload_raw_files(patient_id, snap_json, xps_data,
                              png_images=png_images)
    notify(
        f"Done — {len(xps_data)} XPS + {len(png_images)} PNG(s) + snapshot uploaded."
    )
    return result


# ── Self-test (run directly to verify setup) ──────────────────────────────────

if __name__ == '__main__':
    import sys
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s %(levelname)s: %(message)s')

    print(f"MDB path : {config.MDB_PATH}")
    print(f"XPS dir  : {config.XPS_WATCH_DIR}")
    print()

    try:
        patients = get_recent_patients(hours=48)
    except Exception as e:
        print(f"ERROR reading MDB: {e}")
        print()
        print("Check that MDB_PATH in .env points to the correct lunar.mdb")
        print("and that the Microsoft Access Database Engine is installed.")
        sys.exit(1)

    print(f"Recent patients (last 48 hrs): {len(patients)}")
    for info in patients:
        p   = info['patient']
        pid = p.get('patient_id', '?')
        sd  = info.get('scan_date')
        xps = info['xps_files']
        xps_status = f"{len(xps)} XPS found" if xps else "NO XPS FOUND"
        print(f"  {pid}  {p.get('name','')}  scan={sd}  {xps_status}")

    print()
    print("Setup looks good. Run  python collector_ui.py  to open the upload window.")
