"""
Supabase sync: upload PDF to Storage and upsert patient/scan/bmd_results/report rows.
Uses httpx for storage uploads and supabase-py for DB operations.
"""

import json
import logging
from datetime import datetime, date
from typing import Optional

import httpx
from supabase import create_client, Client, ClientOptions

import config

log = logging.getLogger(__name__)


def _get_client() -> Client:
    return create_client(
        config.SUPABASE_URL,
        config.SUPABASE_KEY,
        options=ClientOptions(postgrest_client_timeout=30),
    )


# ── Duplicate scan check ──────────────────────────────────────────────────
def check_scan_exists(mrn: str, scan_date: str, scan_type: Optional[str] = None) -> bool:
    """
    Return True if a scan already exists in Supabase for this MRN with this exact timestamp.
    If scan_type is provided, also match on scan_type (osteo, total_body, etc).
    scan_date should be an ISO timestamp (e.g. 2026-06-13T11:17:31.977600).
    """
    try:
        headers = {
            'Authorization': f"Bearer {config.SUPABASE_KEY}",
            'apikey':        config.SUPABASE_KEY,
        }
        rest = f"{config.SUPABASE_URL}/rest/v1"

        # Step 1: find patient UUID by MRN
        r = httpx.get(
            f"{rest}/bmd_patients",
            params={'patient_id': f'eq.{mrn}', 'select': 'id'},
            headers=headers, timeout=10,
        )
        r.raise_for_status()
        patients = r.json()
        if not patients:
            return False

        patient_uuid = patients[0]['id']

        # Step 2: look for scan matching date and scan_type
        # Match by date (YYYY-MM-DD) since timestamps may have precision differences
        date_str = str(scan_date)[:10]  # Extract YYYY-MM-DD
        date_start = f'{date_str} 00:00:00+00'
        date_end = f'{date_str} 23:59:59+00'
        params = [
            ('patient_id', f'eq.{patient_uuid}'),
            ('scan_date',  f'gte.{date_start}'),
            ('scan_date',  f'lte.{date_end}'),
            ('select',     'id'),
            ('limit',      '1'),
        ]
        if scan_type:
            params.append(('scan_type', f'eq.{scan_type}'))
        r = httpx.get(
            f"{rest}/bmd_scans",
            params=params,
            headers=headers, timeout=10,
        )
        r.raise_for_status()
        return len(r.json()) > 0

    except Exception as e:
        log.warning("check_scan_exists(%s, %s, %s) failed: %s", mrn, scan_date, scan_type, e)
        return False  # Fail gracefully — assume not uploaded on error


def get_uploaded_mrns() -> set[str]:
    """Return set of all patient MRNs already in Supabase."""
    return set(get_uploaded_mrns_with_type().keys())


def get_uploaded_mrns_with_type() -> dict[str, str]:
    """
    Return {mrn: scan_type} for all patients already in Supabase.
    Queries bmd_patients (has the MRN string) with embedded bmd_scans
    (has scan_type). bmd_scans.patient_id is a UUID FK, not the MRN.
    """
    try:
        headers = {
            'Authorization': f"Bearer {config.SUPABASE_KEY}",
            'apikey':        config.SUPABASE_KEY,
            'Range-Unit':    'items',
            'Prefer':        'count=none',
        }
        rest = f"{config.SUPABASE_URL}/rest/v1"
        r = httpx.get(
            f"{rest}/bmd_patients",
            params={'select': 'patient_id,bmd_scans(scan_type)', 'patient_id': 'not.is.null'},
            headers=headers, timeout=15,
        )
        r.raise_for_status()
        result: dict[str, str] = {}
        for row in r.json():
            mrn   = row.get('patient_id')
            scans = row.get('bmd_scans') or []
            st    = scans[0].get('scan_type', 'osteo') if scans else 'osteo'
            if mrn:
                result[mrn] = st
        return result
    except Exception as e:
        log.warning("get_uploaded_mrns_with_type failed: %s", e)
        return {}


def get_recent_scans_by_source(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> dict:
    """
    Query Supabase for all scans in date range, grouped by source type.
    Includes patient info. Deduplicates XPS scans by (patient_id, scan_date, scan_type),
    keeping latest by created_at (handles re-extracted scans with updated ROIs).

    Returns {
        'xps_scans': [{id, patient_id, scan_date, scan_type, created_at,
                       bmd_patients: {patient_id, first_name, ...}}, ...],
        'archive_scans': [...]
    }

    XPS scans: scan_type NOT IN ('osteo_trend', 'total_body_trend')
    Archive scans: scan_type IN ('osteo_trend', 'total_body_trend')
    """
    try:
        headers = {
            'Authorization': f"Bearer {config.SUPABASE_KEY}",
            'apikey':        config.SUPABASE_KEY,
        }
        rest = f"{config.SUPABASE_URL}/rest/v1"

        # Join bmd_scans with bmd_patients to get patient info
        # Select scan + minimal patient fields
        params = [
            ('select', 'id,patient_id,scan_date,scan_type,xps_filename,created_at,updated_at,'
                      'bmd_patients(patient_id,first_name,last_name,gender,dob)'),
            ('order', 'scan_date.desc,created_at.desc'),
        ]

        if date_from:
            params.append(('scan_date', f'gte.{date_from}T00:00:00Z'))
        if date_to:
            params.append(('scan_date', f'lte.{date_to}T23:59:59Z'))

        # Fetch all scans in range with patient details
        r = httpx.get(
            f"{rest}/bmd_scans",
            params=params,
            headers=headers,
            timeout=15,
        )
        r.raise_for_status()
        all_scans = r.json() or []

        # Separate by source and deduplicate XPS scans
        xps_scans = []
        archive_scans = []
        seen_xps = set()  # (patient_id, scan_date_str, scan_type)

        for scan in all_scans:
            scan_type = scan.get('scan_type', 'osteo')
            is_archive = scan_type in ('osteo_trend', 'total_body_trend')

            if is_archive:
                archive_scans.append(scan)
            else:
                # Deduplicate XPS scans: keep only latest (by created_at) per timestamp
                pid = scan.get('patient_id')
                sdate = str(scan.get('scan_date') or '')[:10]  # YYYY-MM-DD only
                key = (pid, sdate, scan_type)

                if key not in seen_xps:
                    seen_xps.add(key)
                    xps_scans.append(scan)

        return {
            'xps_scans': xps_scans,
            'archive_scans': archive_scans,
        }

    except Exception as e:
        log.warning("get_recent_scans_by_source failed: %s", e)
        return {'xps_scans': [], 'archive_scans': []}


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


def _osteo_scan_type(session: dict) -> str:
    """
    Derive specific osteo scan_type from MDB session.
    Uses the presence of spine / left_femur / right_femur data — all sourced
    from the MDB scantype field, never from XPS content.

      spine + any femur  → 'spine_femur'
      femur(s) only      → 'dual_femur'
      spine only         → 'spine_only'
      unknown            → 'osteo'  (legacy fallback)
    """
    has_spine = bool(session.get('spine'))
    has_femur = bool(session.get('left_femur')) or bool(session.get('right_femur'))
    if has_spine and has_femur:  return 'spine_femur'
    if has_femur:                return 'dual_femur'
    if has_spine:                return 'spine_only'
    return 'osteo'


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
        'scan_type':      _osteo_scan_type(session),
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

    # ── DB upserts via httpx REST (avoids supabase-py connection hangs) ─────
    patient_uuid = scan_uuid = None
    if patient_data and session_data:
        db_headers = {
            'Authorization': f"Bearer {config.SUPABASE_KEY}",
            'apikey':        config.SUPABASE_KEY,
            'Content-Type':  'application/json',
            'Prefer':        'resolution=merge-duplicates,return=representation',
        }
        rest = f"{config.SUPABASE_URL}/rest/v1"

        # ── bmd_patients ──────────────────────────────────────────────────────
        dob = patient_data.get('dob')
        pat_row = {
            'pat_handle':  patient_data.get('pat_handle', f"mrn_{mrn}"),
            'patient_id':  patient_data.get('patient_id', mrn),
            'mrn':         mrn,
            'first_name':  patient_data.get('name', ''),
            'last_name':   patient_data.get('title', ''),
            'dob':         (dob or None) if isinstance(dob, str) else (dob.isoformat() if dob else None),
            'gender':      patient_data.get('gender', ''),
            'ethnicity':   patient_data.get('ethnicity', ''),
            'height_cm':   patient_data.get('height_cm') or None,
            'weight_kg':   patient_data.get('weight_kg') or None,
            'physician':   patient_data.get('physician', ''),
            'updated_at':  datetime.utcnow().isoformat(),
        }
        r = httpx.post(f"{rest}/bmd_patients?on_conflict=pat_handle", headers=db_headers,
                       content=json.dumps(pat_row), timeout=30)
        r.raise_for_status()
        patient_uuid = r.json()[0]['id']
        log.info("Upserted bmd_patients: %s", patient_uuid)

        # ── bmd_scans ────────────────────────────────────────────────────────
        raw_json_str = raw_json.decode()
        scan_date_raw = session_data.get('scan_date', '')
        if hasattr(scan_date_raw, 'strftime'):
            scan_date_str = scan_date_raw.strftime('%Y-%m-%dT%H:%M:%S')
        else:
            scan_date_str = str(scan_date_raw)
        scan_handle = f"{patient_data.get('pat_handle', mrn)}_{scan_date_str[:10]}"
        scan_row = {
            'patient_id':     patient_uuid,
            'scan_handle':    scan_handle,
            'scan_date':      scan_date_str or None,
            'scanner_serial': session_data.get('scanner_serial') or config.SCANNER_ID,
            'software':       session_data.get('software') or config.SOFTWARE,
            'xps_filename':   session_data.get('ntx_filename') or None,
            'scan_type':      _osteo_scan_type(session_data),
            'image_paths':    image_paths,
            'raw_json':       raw_json_str,
        }
        r = httpx.post(f"{rest}/bmd_scans?on_conflict=scan_handle", headers=db_headers,
                       content=json.dumps(scan_row), timeout=30)
        r.raise_for_status()
        scan_uuid = r.json()[0]['id']
        log.info("Upserted bmd_scans: %s", scan_uuid)

        # ── bmd_results ──────────────────────────────────────────────────────
        sb = _get_client()
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
    notify=None,
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
    _n = notify or (lambda m: log.info(m))

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
    _n(f"  Uploading raw_totalbody.json ({len(raw_json)//1024} KB)…")
    _put(f"{prefix}/raw_totalbody.json", raw_json, "application/json")

    _img_key = {
        'img_fat_lean.png':     'fat_lean',
        'img_fat_gradient.png': 'fat_gradient',
        'img_bone.png':         'bone',
        'img_composite.png':    'composite',
    }
    image_paths: dict[str, str] = {}
    for fname, data in (png_images or {}).items():
        _n(f"  Uploading {fname} ({len(data)//1024} KB)…")
        storage_path = f"{prefix}/{fname}"
        _put(storage_path, data, "image/png")
        key = _img_key.get(fname, fname.replace('img_', '').replace('.png', ''))
        image_paths[key] = storage_path

    for fname, data in xps_files.items():
        _n(f"  Uploading {fname} ({len(data)//1024} KB)…")
        _put(f"{prefix}/{fname}", data, "application/octet-stream")

    n_files = 1 + len(xps_files) + len(image_paths)
    log.info("Total-body raw upload complete: %s (%d files)", prefix, n_files)

    # DB upserts — use httpx directly (same as storage) to avoid supabase-py hangs
    patient_uuid = scan_uuid = None
    if patient_data and session_data:
        db_headers = {
            'Authorization': f"Bearer {config.SUPABASE_KEY}",
            'apikey':        config.SUPABASE_KEY,
            'Content-Type':  'application/json',
            'Prefer':        'resolution=merge-duplicates,return=representation',
        }
        rest = f"{config.SUPABASE_URL}/rest/v1"

        _n("  Upserting patient record…")
        dob = patient_data.get('dob')
        pat_row = {
            'pat_handle':  patient_data.get('pat_handle', f"mrn_{mrn}"),
            'patient_id':  patient_data.get('patient_id', mrn),
            'mrn':         mrn,
            'first_name':  patient_data.get('name', ''),
            'last_name':   patient_data.get('title', ''),
            'dob':         (dob or None) if isinstance(dob, str) else (dob.isoformat() if dob else None),
            'gender':      patient_data.get('gender', ''),
            'height_cm':   patient_data.get('height_cm') or None,
            'weight_kg':   patient_data.get('weight_kg') or None,
            'physician':   patient_data.get('physician', ''),
            'updated_at':  datetime.utcnow().isoformat(),
        }
        r = httpx.post(f"{rest}/bmd_patients?on_conflict=pat_handle", headers=db_headers,
                       content=json.dumps(pat_row, default=str), timeout=30)
        r.raise_for_status()
        patient_uuid = r.json()[0]['id']
        log.info("Upserted bmd_patients: %s", patient_uuid)
        _n("  Patient record saved. Upserting scan record…")

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
        r = httpx.post(f"{rest}/bmd_scans?on_conflict=scan_handle", headers=db_headers,
                       content=json.dumps(scan_row), timeout=30)
        r.raise_for_status()
        scan_uuid = r.json()[0]['id']
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


# ── Trend scan upload (MDB-only, no images) ───────────────────────────────────

def upload_patient_trend(patient_id: str, scan_type: str,
                        progress_cb=None, mdb_path: str = None) -> dict:
    """
    Upload MDB-only trend data for a patient from the specified MDB.
    Extracts patient data from MDB, converts to raw JSON, and uploads as trend.

    @param patient_id: MRN or patient ID
    @param scan_type: 'osteo_trend' or 'total_body_trend'
    @param progress_cb: optional callback for progress messages
    @param mdb_path: path to archive MDB file (required)
    @returns: result dict from upload_trend_scan
    """
    from parse_mdb import MdbParser
    import json

    notify = progress_cb or (lambda m: log.info(m))

    if not mdb_path:
        raise ValueError('mdb_path required for archive trend upload')

    notify(f'Reading archive MDB from {mdb_path}')
    parser = MdbParser(mdb_path)

    # Find patient in archive
    pat_handles = [
        ph for ph, row in parser._patients.items()
        if row.get('patient_id', '').strip() == str(patient_id)
    ]
    if not pat_handles:
        raise RuntimeError(f'Patient {patient_id} not found in archive MDB')

    # Get patient data and sessions
    pat_handle = pat_handles[0]
    patient_row = parser._patients[pat_handle]
    pat = parser._parse_patient(patient_row)
    sessions = parser.get_scan_sessions(pat_handle)

    if not sessions:
        raise RuntimeError(f'No sessions found for {patient_id} in archive MDB')

    # Find session matching requested scan type
    expected_type = 'osteo' if scan_type == 'osteo_trend' else 'total_body'
    matching_sessions = [s for s in sessions if s.get('mdb_scan_type') == expected_type]
    if not matching_sessions:
        available = ', '.join(set(s.get('mdb_scan_type', 'unknown') for s in sessions))
        raise RuntimeError(
            f'Archive patient {patient_id} has no {expected_type} scan. Available: {available}'
        )
    latest_session = matching_sessions[0]

    # Build raw JSON snapshot (same structure as fetch)
    raw_data = {
        'mdb_snapshot': {
            'patient_id': patient_id,
            'snapshot_ts': str(parser.snapshot_ts),
            'patients': {pat_handle: patient_row},
            'exams': parser.exams,
            'composition': parser._composition,
            'densitometry': parser._densitometry,
        },
        'patient': {
            'pat_handle': pat['pat_handle'],
            'patient_id': pat['patient_id'],
            'mrn': str(patient_id),
            'name': pat.get('name', ''),
            'title': pat.get('title', ''),
            'dob': pat['dob'].isoformat() if pat.get('dob') else '',
            'gender': pat.get('gender', 'Female'),
            'ethnicity': pat.get('ethnicity', ''),
            'height_cm': pat.get('height_cm') or 0,
            'weight_kg': pat.get('weight_kg') or 0,
            'bmi': pat.get('bmi') or 0,
            'physician': pat.get('physician', ''),
        },
        'session': {
            'scan_date': latest_session.get('scan_date', ''),
            'scanner_serial': latest_session.get('scanner_serial') or config.SCANNER_ID,
            'software': latest_session.get('software') or config.SOFTWARE,
            'ntx_filename': latest_session.get('ntx_filename'),
            'spine': latest_session.get('spine', {}),
            'left_femur': latest_session.get('left_femur', {}),
            'right_femur': latest_session.get('right_femur', {}),
            'estimated_composition': latest_session.get('estimated_composition', {}),
        }
    }

    raw_json_bytes = json.dumps(raw_data, indent=2, default=str).encode()
    notify(f'Uploading {scan_type} for {patient_id}')

    return upload_trend_scan(str(patient_id), raw_json_bytes, scan_type, progress_cb=progress_cb)


def upload_trend_scan(mrn: str, raw_json_bytes: bytes, scan_type: str,
                      progress_cb=None) -> dict:
    """
    Upload MDB-only historical data as a trend record — no Storage, no XPS.
    Creates bmd_scans rows only (no bmd_patients entry).
    Links to existing patient by MRN if available, otherwise creates scan without patient_id.
    scan_type must be 'osteo_trend' or 'total_body_trend'.
    Returns {'patient_uuid', 'scan_uuid', 'scan_type'}.
    """
    notify = progress_cb or log.info

    snapshot = json.loads(raw_json_bytes)

    # Extract patient + first exam from snapshot
    pat_handle = next(iter(snapshot.get('patients', {}).keys()), f'mrn_{mrn}')
    first_exam   = (snapshot.get('exams') or [{}])[0]

    scan_date_raw = first_exam.get('_acq_dt', '')
    scan_date_str = str(scan_date_raw)[:19]          # 'YYYY-MM-DDTHH:MM:SS'

    db_headers = {
        'Authorization': f'Bearer {config.SUPABASE_KEY}',
        'apikey':        config.SUPABASE_KEY,
        'Content-Type':  'application/json',
        'Prefer':        'resolution=merge-duplicates,return=representation',
    }
    rest = f'{config.SUPABASE_URL}/rest/v1'

    # Find existing patient by MRN
    patient_uuid = None
    try:
        r = httpx.get(f'{rest}/bmd_patients?mrn=eq.{mrn}&select=id',
                      headers=db_headers, timeout=10)
        r.raise_for_status()
        patients = r.json()
        if patients:
            patient_uuid = patients[0]['id']
            notify(f'  Linked to existing patient {mrn}: {patient_uuid}')
        else:
            notify(f'  Warning: patient {mrn} not found in bmd_patients - scan will be created without patient link')
    except Exception as e:
        notify(f'  Warning: error searching for patient {mrn}: {e}')

    # ── bmd_scans ─────────────────────────────────────────────────────────────
    # Suffix '_t' distinguishes trend handle from a real scan on the same date
    scan_handle = f'{pat_handle}_{scan_date_str[:10]}_t'
    scan_row = {
        'scan_handle': scan_handle,
        'scan_date':   scan_date_str or None,
        'scan_type':   scan_type,
        'image_paths': {},
        'raw_json':    snapshot,  # Pass dict, not string, so JSONB stores properly
        'updated_at':  datetime.utcnow().isoformat(),
    }
    if patient_uuid:
        scan_row['patient_id'] = patient_uuid

    r = httpx.post(f'{rest}/bmd_scans?on_conflict=scan_handle',
                   headers=db_headers, content=json.dumps(scan_row), timeout=30)
    r.raise_for_status()
    scan_uuid = r.json()[0]['id']
    notify(f'  Scan upserted: {scan_uuid} ({scan_type})')

    return {'patient_uuid': patient_uuid, 'scan_uuid': scan_uuid,
            'scan_type': scan_type}
