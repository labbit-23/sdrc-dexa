"""
Supabase sync: upload PDF to Storage and upsert patient/scan/bmd_results/report rows.
Uses httpx for storage uploads and supabase-py for DB operations.
"""

import json
import logging
from datetime import datetime, date
from typing import Optional

import httpx
from supabase import create_client, Client

import config

log = logging.getLogger(__name__)


def _get_client() -> Client:
    return create_client(config.SUPABASE_URL, config.SUPABASE_KEY)


# ── PDF storage ───────────────────────────────────────────────────────────
def upload_pdf(patient_id: str, scan_date: datetime, pdf_bytes: bytes) -> str:
    """Upload PDF to Supabase Storage bucket 'pdfs'. Returns public URL."""
    dt_str = scan_date.strftime('%Y-%m-%d_%H%M') if scan_date else 'unknown'
    path = f"bmd-pdfs/{patient_id}/{dt_str}.pdf"

    headers = {
        "Authorization": f"Bearer {config.SUPABASE_KEY}",
        "Content-Type": "application/pdf",
    }
    url = f"{config.SUPABASE_URL}/storage/v1/object/{path}"

    r = httpx.put(url, headers=headers, content=pdf_bytes, timeout=60)
    if r.status_code == 400 and 'already exists' in r.text:
        r = httpx.put(url + "?upsert=true", headers=headers, content=pdf_bytes, timeout=60)
    r.raise_for_status()

    public_url = f"{config.SUPABASE_URL}/storage/v1/object/public/{path}"
    log.info("Uploaded PDF → %s", public_url)
    return public_url


# ── DB upserts ────────────────────────────────────────────────────────────
def _ser(v):
    """JSON-serialisable helper."""
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return v


def upsert_patient(sb: Client, patient: dict) -> str:
    """Upsert patient row. Returns Supabase patient UUID."""
    dob = patient.get('dob')
    row = {
        'pat_handle':  patient['pat_handle'],
        'patient_id':  patient.get('patient_id', ''),
        'first_name':  patient.get('name', ''),
        'last_name':   patient.get('title', ''),
        'dob':         dob.isoformat() if isinstance(dob, date) else dob,
        'gender':      patient.get('gender', ''),
        'ethnicity':   patient.get('ethnicity', ''),
        'height_cm':   patient.get('height_cm'),
        'weight_kg':   patient.get('weight_kg'),
        'physician':   patient.get('physician', ''),
        'updated_at':  datetime.utcnow().isoformat(),
    }
    result = (
        sb.table('bmd_patients')
        .upsert(row, on_conflict='pat_handle')
        .execute()
    )
    return result.data[0]['id']


def upsert_scan(sb: Client, patient_uuid: str, session: dict) -> str:
    """Upsert scan row. Returns Supabase scan UUID."""
    scan_date = session.get('scan_date')
    row = {
        'patient_id':     patient_uuid,
        'scan_handle':    session['scan_handle'],
        'scan_date':      scan_date.isoformat() if scan_date else None,
        'scanner_serial': session.get('scanner_serial') or config.SCANNER_ID,
        'software':       session.get('software') or config.SOFTWARE,
        'xps_filename':   session.get('xps_filename') or session.get('ntx_filename'),
        'raw_json':       json.dumps(session, default=_ser),
    }
    result = (
        sb.table('bmd_scans')
        .upsert(row, on_conflict='scan_handle')
        .execute()
    )
    return result.data[0]['id']


def upsert_bmd_results(sb: Client, scan_uuid: str, merged: dict):
    """Upsert all BMD result rows for a scan."""
    rows = []

    def _add(region_data: dict, side: Optional[str]):
        for site, v in region_data.items():
            if not v:
                continue
            rows.append({
                'scan_id':   scan_uuid,
                'site':      site,
                'side':      side,
                'bmd':       v.get('bmd'),
                'bmc':       v.get('bmc'),
                'area':      v.get('area'),
                't_score':   v.get('T'),
                'z_score':   v.get('Z'),
                'pct_ya':    v.get('pYA'),
                'source':    v.get('source', 'MDB'),
            })

    _add(merged.get('spine', {}),       None)
    _add(merged.get('left_femur', {}),  'left')
    _add(merged.get('right_femur', {}), 'right')

    if rows:
        # Delete existing results for this scan then re-insert
        sb.table('bmd_results').delete().eq('scan_id', scan_uuid).execute()  # already prefixed
        sb.table('bmd_results').insert(rows).execute()
        log.info("Upserted %d BMD result rows for scan %s", len(rows), scan_uuid)


def upsert_report(sb: Client, scan_uuid: str, pdf_url: str) -> str:
    """Insert report row. Returns report UUID."""
    row = {
        'scan_id':           scan_uuid,
        'pdf_url':           pdf_url,
        'generated_at':      datetime.utcnow().isoformat(),
        'generator_version': config.GENERATOR_VER,
    }
    result = sb.table('bmd_reports').insert(row).execute()
    return result.data[0]['id']


# ── Raw file upload (Windows collector → Supabase Storage) ───────────────────

def upload_raw_files(patient_id: str, mdb_snapshot_json: bytes,
                     xps_files: dict[str, bytes],
                     png_images: dict[str, bytes] | None = None) -> dict:
    """
    Upload raw MDB snapshot + XPS bytes to Supabase Storage.
    Storage layout:
      raw/{patient_id}/{ts}/mdb_snapshot.json
      raw/{patient_id}/{ts}/{xps_filename}

    Called from the Windows collector — no analysis, no PDF.
    The remote processor on Mac/server picks these up and runs the pipeline.

    Returns dict: {storage_prefix, files_uploaded}
    """
    ts     = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    prefix = f"raw/{patient_id}/{ts}"
    headers_base = {
        "Authorization": f"Bearer {config.SUPABASE_KEY}",
    }

    def _put(path: str, content: bytes, content_type: str):
        url = f"{config.SUPABASE_URL}/storage/v1/object/{path}"
        h = {**headers_base, "Content-Type": content_type}
        r = httpx.put(url, headers=h, content=content, timeout=120)
        if r.status_code == 400 and 'already exists' in r.text:
            r = httpx.put(url + "?upsert=true", headers=h, content=content, timeout=120)
        r.raise_for_status()
        log.info("Uploaded raw file → %s", path)

    _put(f"{prefix}/mdb_snapshot.json", mdb_snapshot_json, "application/json")

    for fname, data in xps_files.items():
        _put(f"{prefix}/{fname}", data, "application/octet-stream")

    for fname, data in (png_images or {}).items():
        _put(f"{prefix}/{fname}", data, "image/png")

    n_files = 1 + len(xps_files) + len(png_images or {})
    log.info("Raw upload complete: %s (%d files total)", prefix, n_files)
    return {
        'storage_prefix':  prefix,
        'files_uploaded':  n_files,
        'png_keys':        [f"{prefix}/{f}" for f in (png_images or {})],
    }


# ── Osteo raw upload (Windows collector → Supabase) ─────────────────────────

def upload_osteo_raw(
    mrn:          str,
    raw_json:     bytes,
    xps_files:    dict[str, bytes],
    png_images:   dict[str, bytes] | None = None,
    patient_data: dict | None = None,
    session_data: dict | None = None,
) -> dict:
    """
    Upload raw osteo data for one patient:
      • raw_osteo.json        → Supabase Storage (bucket: raw-osteo)
      • img_spine.png etc.    → Supabase Storage
      • raw XPS bytes         → Supabase Storage
      • bmd_patients row      → upserted with mrn
      • bmd_scans row         → upserted with scan_type='osteo' + image_paths
      • bmd_results rows      → replaced for this scan

    Storage layout:
      raw-osteo/{mrn}/{timestamp}/raw_osteo.json
      raw-osteo/{mrn}/{timestamp}/img_spine.png
      raw-osteo/{mrn}/{timestamp}/img_left_femur.png
      raw-osteo/{mrn}/{timestamp}/img_right_femur.png
      raw-osteo/{mrn}/{timestamp}/{xps_filename}

    Returns dict: {storage_prefix, files_uploaded, patient_uuid, scan_uuid}
    """
    import json as _json

    ts     = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    bucket = 'raw-osteo'
    prefix = f"raw-osteo/{mrn}/{ts}"

    headers_base = {"Authorization": f"Bearer {config.SUPABASE_KEY}"}

    def _put(path: str, content: bytes, content_type: str):
        url = f"{config.SUPABASE_URL}/storage/v1/object/{path}"
        h = {**headers_base, "Content-Type": content_type}
        r = httpx.put(url, headers=h, content=content, timeout=120)
        if r.status_code == 400 and 'already exists' in r.text:
            r = httpx.put(url + "?upsert=true", headers=h, content=content, timeout=120)
        r.raise_for_status()
        log.info("Uploaded → %s", path)

    # ── Storage uploads ──────────────────────────────────────────────────────
    _put(f"{prefix}/raw_osteo.json", raw_json, "application/json")

    image_paths: dict[str, str] = {}

    # Strip-assembled scan images (keyed by label)
    label_to_file = {
        'spine':       'img_spine.png',
        'left_femur':  'img_left_femur.png',
        'right_femur': 'img_right_femur.png',
    }
    for label, fname in label_to_file.items():
        if label in (png_images or {}):
            storage_path = f"{prefix}/{fname}"
            _put(storage_path, png_images[label], "image/png")     # type: ignore[index]
            image_paths[label] = storage_path

    # Overlay pages (mutool-rendered, ROI lines baked in; keyed by filename)
    overlay_files = {
        'img_spine_overlay.png':       'spine_overlay',
        'img_left_femur_overlay.png':  'left_femur_overlay',
        'img_right_femur_overlay.png': 'right_femur_overlay',
    }
    for fname, key in overlay_files.items():
        if fname in (png_images or {}):
            storage_path = f"{prefix}/{fname}"
            _put(storage_path, png_images[fname], "image/png")     # type: ignore[index]
            image_paths[key] = storage_path

    for fname, data in xps_files.items():
        _put(f"{prefix}/{fname}", data, "application/octet-stream")

    n_files = 1 + len(xps_files) + len(image_paths)
    log.info("Osteo raw upload complete: %s (%d files)", prefix, n_files)

    # ── DB upserts (if patient + session data provided) ──────────────────────
    patient_uuid = scan_uuid = None
    if patient_data and session_data:
        sb = _get_client()

        # ── bmd_patients (upsert on pat_handle; also set mrn) ────────────────
        dob = patient_data.get('dob')
        pat_row = {
            'pat_handle':  patient_data.get('pat_handle', f"mrn_{mrn}"),
            'patient_id':  patient_data.get('patient_id', mrn),
            'mrn':         mrn,
            'first_name':  patient_data.get('name', ''),
            'last_name':   patient_data.get('title', ''),
            'dob':         dob if isinstance(dob, str) else (dob.isoformat() if dob else None),
            'gender':      patient_data.get('gender', ''),
            'ethnicity':   patient_data.get('ethnicity', ''),
            'height_cm':   patient_data.get('height_cm') or None,
            'weight_kg':   patient_data.get('weight_kg') or None,
            'physician':   patient_data.get('physician', ''),
            'updated_at':  datetime.utcnow().isoformat(),
        }
        res = (
            sb.table('bmd_patients')
            .upsert(pat_row, on_conflict='pat_handle')
            .execute()
        )
        patient_uuid = res.data[0]['id']
        log.info("Upserted bmd_patients: %s", patient_uuid)

        # ── bmd_scans ────────────────────────────────────────────────────────
        # raw_json bytes are already JSON-encoded; decode to string for TEXT column.
        # Do NOT re-parse+re-dump — that can double-encode if raw_json is a string.
        raw_json_str = raw_json.decode()
        scan_date_raw = session_data.get('scan_date', '')
        # Convert datetime to string if needed
        if hasattr(scan_date_raw, 'strftime'):
            scan_date_str = scan_date_raw.strftime('%Y-%m-%dT%H:%M:%S')
        else:
            scan_date_str = str(scan_date_raw)
        # scan_handle: use pat_handle + scan_date as a stable key
        scan_handle = f"{patient_data.get('pat_handle', mrn)}_{scan_date_str[:10]}"
        scan_row = {
            'patient_id':     patient_uuid,
            'scan_handle':    scan_handle,
            'scan_date':      scan_date_str or None,
            'scanner_serial': session_data.get('scanner_serial') or config.SCANNER_ID,
            'software':       session_data.get('software') or config.SOFTWARE,
            'xps_filename':   session_data.get('ntx_filename') or None,
            'scan_type':      'osteo',
            'image_paths':    image_paths,            # dict → stored as JSONB object
            'raw_json':       raw_json_str,           # TEXT column — already JSON string
        }
        res = (
            sb.table('bmd_scans')
            .upsert(scan_row, on_conflict='scan_handle')
            .execute()
        )
        scan_uuid = res.data[0]['id']
        log.info("Upserted bmd_scans: %s", scan_uuid)

        # ── bmd_results ──────────────────────────────────────────────────────
        rows = []
        def _add(region_data: dict, side):
            for site, v in region_data.items():
                if not v:
                    continue
                rows.append({
                    'scan_id':  scan_uuid,
                    'site':     site,
                    'side':     side,
                    'bmd':      v.get('bmd'),
                    'bmc':      v.get('bmc'),
                    'area':     v.get('area'),
                    't_score':  v.get('T'),
                    'z_score':  v.get('Z'),
                    'pct_ya':   v.get('pYA'),
                    'source':   'MDB',
                })

        _add(session_data.get('spine', {}),       None)
        _add(session_data.get('left_femur', {}),  'left')
        _add(session_data.get('right_femur', {}), 'right')

        if rows:
            sb.table('bmd_results').delete().eq('scan_id', scan_uuid).execute()
            sb.table('bmd_results').insert(rows).execute()
            log.info("Inserted %d bmd_results rows for scan %s", len(rows), scan_uuid)

    return {
        'storage_prefix': prefix,
        'files_uploaded': n_files,
        'patient_uuid':   patient_uuid,
        'scan_uuid':      scan_uuid,
    }


# ── Total-body raw upload ─────────────────────────────────────────────────────

def upload_totalbody_raw(
    mrn:          str,
    raw_json:     bytes,
    xps_files:    dict[str, bytes],
    png_images:   dict[str, bytes] | None = None,
    patient_data: dict | None = None,
    session_data: dict | None = None,
) -> dict:
    """
    Upload raw total-body data for one patient (mirrors upload_osteo_raw):
      • raw_totalbody.json  → Supabase Storage (bucket: raw-totalbody)
      • img_fat_lean.png etc → Supabase Storage
      • raw XPS bytes        → Supabase Storage
      • bmd_patients row     → upserted with mrn
      • bmd_scans row        → upserted with scan_type='total_body' + image_paths

    image_paths keys: fat_lean, fat_gradient, bone, composite
    """
    ts     = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    bucket = 'raw-totalbody'
    prefix = f"raw-totalbody/{mrn}/{ts}"

    headers_base = {"Authorization": f"Bearer {config.SUPABASE_KEY}"}

    def _put(path: str, content: bytes, content_type: str):
        url = f"{config.SUPABASE_URL}/storage/v1/object/{path}"
        h = {**headers_base, "Content-Type": content_type}
        r = httpx.put(url, headers=h, content=content, timeout=120)
        if r.status_code == 400 and 'already exists' in r.text:
            r = httpx.put(url + "?upsert=true", headers=h, content=content, timeout=120)
        r.raise_for_status()
        log.info("Uploaded → %s", path)

    # Storage uploads
    _put(f"{prefix}/raw_totalbody.json", raw_json, "application/json")

    _img_key = {          # filename → image_paths key
        'img_fat_lean.png':     'fat_lean',
        'img_fat_gradient.png': 'fat_gradient',
        'img_bone.png':         'bone',
        'img_composite.png':    'composite',
    }
    image_paths: dict[str, str] = {}
    for fname, data in (png_images or {}).items():
        storage_path = f"{prefix}/{fname}"
        _put(storage_path, data, "image/png")
        key = _img_key.get(fname, fname.replace('img_', '').replace('.png', ''))
        image_paths[key] = storage_path

    for fname, data in xps_files.items():
        _put(f"{prefix}/{fname}", data, "application/octet-stream")

    n_files = 1 + len(xps_files) + len(image_paths)
    log.info("Total-body raw upload complete: %s (%d files)", prefix, n_files)

    # DB upserts
    patient_uuid = scan_uuid = None
    if patient_data and session_data:
        sb = _get_client()

        dob = patient_data.get('dob')
        pat_row = {
            'pat_handle':  patient_data.get('pat_handle', f"mrn_{mrn}"),
            'patient_id':  patient_data.get('patient_id', mrn),
            'mrn':         mrn,
            'first_name':  patient_data.get('name', ''),
            'last_name':   patient_data.get('title', ''),
            'dob':         dob if isinstance(dob, str) else (dob.isoformat() if dob else None),
            'gender':      patient_data.get('gender', ''),
            'height_cm':   patient_data.get('height_cm') or None,
            'weight_kg':   patient_data.get('weight_kg') or None,
            'physician':   patient_data.get('physician', ''),
            'updated_at':  datetime.utcnow().isoformat(),
        }
        res = sb.table('bmd_patients').upsert(pat_row, on_conflict='pat_handle').execute()
        patient_uuid = res.data[0]['id']
        log.info("Upserted bmd_patients: %s", patient_uuid)

        raw_json_str = raw_json.decode()
        scan_date_raw = session_data.get('scan_date', '')
        if hasattr(scan_date_raw, 'strftime'):
            scan_date_str = scan_date_raw.strftime('%Y-%m-%dT%H:%M:%S')
        else:
            scan_date_str = str(scan_date_raw)

        scan_handle = f"{patient_data.get('pat_handle', mrn)}_tb_{scan_date_str[:10]}"
        scan_row = {
            'patient_id':     patient_uuid,
            'scan_handle':    scan_handle,
            'scan_date':      scan_date_str or None,
            'scanner_serial': session_data.get('scanner_serial') or config.SCANNER_ID,
            'software':       session_data.get('software') or config.SOFTWARE,
            'scan_type':      'total_body',
            'image_paths':    image_paths,
            'raw_json':       raw_json_str,
        }
        res = sb.table('bmd_scans').upsert(scan_row, on_conflict='scan_handle').execute()
        scan_uuid = res.data[0]['id']
        log.info("Upserted bmd_scans (total_body): %s", scan_uuid)

    return {
        'storage_prefix': prefix,
        'files_uploaded': n_files,
        'patient_uuid':   patient_uuid,
        'scan_uuid':      scan_uuid,
    }


# ── High-level sync ───────────────────────────────────────────────────────
def sync_scan(patient: dict, session: dict, merged: dict, pdf_bytes: bytes) -> dict:
    """
    Full sync pipeline:
      1. Upload PDF to Storage
      2. Upsert patient, scan, bmd_results, report rows
    Returns dict with Supabase UUIDs and PDF URL.
    """
    sb = _get_client()

    pid = patient.get('patient_id') or patient.get('pat_handle', 'unknown')
    scan_date = session.get('scan_date')

    pdf_url      = upload_pdf(pid, scan_date, pdf_bytes)
    patient_uuid = upsert_patient(sb, patient)
    scan_uuid    = upsert_scan(sb, patient_uuid, session)
    upsert_bmd_results(sb, scan_uuid, merged)
    report_uuid  = upsert_report(sb, scan_uuid, pdf_url)

    log.info("Sync complete: patient=%s scan=%s report=%s",
             patient_uuid, scan_uuid, report_uuid)
    return {
        'patient_uuid': patient_uuid,
        'scan_uuid':    scan_uuid,
        'report_uuid':  report_uuid,
        'pdf_url':      pdf_url,
    }
