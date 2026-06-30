"""
Osteo (spine + hip) data collector — Windows side only.

Reads the GE Lunar MDB for a patient's spine/femur densitometry data,
finds the three XPS files (spine, left femur, right femur) in the
designated XPS folder, extracts scan images, and uploads everything to
Supabase Storage + DB tables.

XPS file detection strategy
────────────────────────────
Files are matched by *modification time*, not by filename.
Staff just use File → Save As → XPS in GE Lunar with any name.
The collector looks for XPS files in XPS_WATCH_DIR modified on the
same calendar day as the MDB scan date (or within the last 7 days as
a fallback), then classifies them by embedded text content.

After a successful upload the caller should clear the watch folder
(or the UI prompts the operator to do so) so old files don't bleed
into the next patient's collection.

Storage layout per upload:
  raw-osteo/{mrn}/{timestamp}/
    raw_osteo.json          — full MDB data for this patient + session
    img_spine.png           — extracted spine DXA image
    img_left_femur.png      — extracted left femur DXA image
    img_right_femur.png     — extracted right femur DXA image
    <original-xps-name>.xps — raw XPS files (kept for reprocessing)

Usage from the UI (collector_osteo_ui.py) or CLI:
  python collect_osteo.py <mrn>           # mrn == patient_id from GE Lunar
"""

import io
import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import config
from parse_mdb import list_patient_sessions, MdbParser
from parse_xps import extract_xps_text, extract_osteo_images, render_osteo_overlay_pages

log = logging.getLogger(__name__)


# ─── XPS detection ────────────────────────────────────────────────────────────

XPS_LABELS = ('spine', 'left_femur', 'right_femur')

def _classify_xps(xps_path: str) -> str:
    """
    Read text from an XPS file and classify it as
    'spine' | 'left_femur' | 'right_femur' | 'combined' | 'dual_femur' | 'unknown'.

    GE Lunar often produces combined XPS files containing all three scan
    types (AP Spine + Left Femur + Right Femur) in a single document.
    These are classified as 'combined' and used for all three slots.
    A dual-femur-only XPS (no spine) is classified as 'dual_femur'.
    """
    try:
        tokens = ' '.join(t for _, _, t in extract_xps_text(xps_path))
    except Exception as e:
        log.warning("Could not read XPS text from %s: %s", xps_path, e)
        return 'unknown'
    has_spine  = any(x in tokens for x in ['Lumbar', 'Spine', 'lumbar', 'spine', 'AP Spine'])
    has_femur  = any(x in tokens for x in ['Femur', 'femur', 'Neck', 'Trochanter'])
    has_left   = any(x in tokens for x in ['Left', 'left', 'LEFT'])
    has_right  = any(x in tokens for x in ['Right', 'right', 'RIGHT'])
    if has_spine and has_femur and has_left and has_right:
        return 'combined'
    if has_spine and not has_femur:
        return 'spine'
    if has_femur and has_left and has_right and not has_spine:
        return 'dual_femur'
    if has_femur and has_left and not has_right:
        return 'left_femur'
    if has_femur and has_right and not has_left:
        return 'right_femur'
    return 'unknown'


def detect_osteo_xps(
    xps_dir: Optional[str] = None,
    scan_date: Optional[datetime] = None,
    mrn: Optional[str] = None,
) -> dict[str, str]:
    """
    Find spine + femur XPS files in *xps_dir*.

    Strategy
    ────────
    1. All .xps files in the watch folder, newest-mtime first.
    2. **REQUIRED**: if mrn is provided, only consider files whose filename
       contains the MRN.  This prevents a previous patient's XPS files from
       being attached to the current patient.
    3. Narrow further by mtime to the scan_date calendar day (or 7-day window).
    4. Classify by embedded text ('spine' / 'left_femur' / 'right_femur' / 'combined').

    Returns dict with up to three keys:
      {'spine': '/abs/path.xps', 'left_femur': '...', 'right_femur': '...'}
    """
    watch = Path(xps_dir or config.XPS_WATCH_DIR)
    if not watch.exists():
        log.warning("XPS watch dir does not exist: %s", watch)
        return {}

    all_xps = sorted(
        watch.glob('*.xps'),
        key=lambda p: p.stat().st_mtime,
        reverse=True,      # newest first
    )
    if not all_xps:
        log.info("No XPS files in %s", watch)
        return {}

    # ── Step 2: filter by MRN in filename (mandatory when mrn is known) ───────
    if mrn:
        mrn_xps = [p for p in all_xps if mrn in p.name]
        if mrn_xps:
            log.info("XPS filter: %d file(s) contain MRN %s in filename", len(mrn_xps), mrn)
            all_xps = mrn_xps
        else:
            log.warning(
                "No XPS files contain MRN %s in filename — refusing to use "
                "unrelated files.  Ask staff to save XPS with MRN in the filename.", mrn
            )
            return {}

    # ── Step 3: narrow by mtime ───────────────────────────────────────────────
    if scan_date:
        target_date = scan_date.date() if isinstance(scan_date, datetime) else scan_date
        candidates = [
            p for p in all_xps
            if datetime.fromtimestamp(p.stat().st_mtime).date() == target_date
        ]
        if not candidates:
            log.info("No XPS modified on %s — widening to 7-day window", target_date)
            cutoff = datetime.now() - timedelta(days=7)
            candidates = [
                p for p in all_xps
                if datetime.fromtimestamp(p.stat().st_mtime) >= cutoff
            ]
    else:
        cutoff = datetime.now() - timedelta(days=7)
        candidates = [
            p for p in all_xps
            if datetime.fromtimestamp(p.stat().st_mtime) >= cutoff
        ]

    if not candidates:
        log.info("No recent XPS — using all MRN-matched files as fallback")
        candidates = all_xps[:9]

    from parse_xps import _has_scan_images

    combined_no_images: Optional[str] = None
    per_scan: dict[str, str] = {}

    # ── Pass 1: prefer combined XPS with embedded images (always wins) ────────
    for xps_path in candidates:
        label = _classify_xps(str(xps_path))
        abs_path = str(xps_path.resolve())
        mtime_str = datetime.fromtimestamp(xps_path.stat().st_mtime).strftime('%Y-%m-%d %H:%M')
        if label == 'dual_femur':
            if _has_scan_images(abs_path):
                log.info("  %s → dual_femur + images  (modified %s)", xps_path.name, mtime_str)
                return {'left_femur': abs_path, 'right_femur': abs_path}
            elif combined_no_images is None:
                log.info("  %s → dual_femur (text only)  (modified %s)", xps_path.name, mtime_str)
                combined_no_images = abs_path
        elif label == 'combined':
            if _has_scan_images(abs_path):
                log.info("  %s → combined + images  (modified %s)", xps_path.name, mtime_str)
                return {'spine': abs_path, 'left_femur': abs_path, 'right_femur': abs_path}
            elif combined_no_images is None:
                log.info("  %s → combined (text only)  (modified %s)", xps_path.name, mtime_str)
                combined_no_images = abs_path

    # ── Pass 2: per-scan individual files ────────────────────────────────────
    # Prefer image-bearing XPS over text-only for each label slot.
    per_scan_has_imgs: dict[str, bool] = {}
    for xps_path in candidates:
        label = _classify_xps(str(xps_path))
        abs_path = str(xps_path.resolve())
        mtime_str = datetime.fromtimestamp(xps_path.stat().st_mtime).strftime('%Y-%m-%d %H:%M')
        if label not in XPS_LABELS:
            continue
        has_imgs = _has_scan_images(abs_path)
        if label not in per_scan:
            per_scan[label] = abs_path
            per_scan_has_imgs[label] = has_imgs
            log.info("  %s → %s%s  (modified %s)", xps_path.name, label,
                     " [+images]" if has_imgs else "", mtime_str)
        elif has_imgs and not per_scan_has_imgs.get(label):
            # Upgrade: existing slot is text-only; this one has images — prefer it
            log.info("  %s → %s [upgraded, has images]  (modified %s)", xps_path.name, label, mtime_str)
            per_scan[label] = abs_path
            per_scan_has_imgs[label] = True

    if per_scan:
        return per_scan

    # ── Pass 3: text-only combined (no images, but has BMD data) ─────────────
    if combined_no_images:
        log.warning("Only text-only combined XPS found — no scan images will be extracted")
        return {'spine': combined_no_images, 'left_femur': combined_no_images, 'right_femur': combined_no_images}

    return {}


def xps_status(
    xps_dir: Optional[str] = None,
    scan_date: Optional[datetime] = None,
    mrn: Optional[str] = None,
) -> dict:
    """
    Return a status dict suitable for the UI.

    Shape:
      {
        'found':   {'spine': '/path', 'left_femur': '/path', ...},
        'missing': ['right_femur'],
        'ready':   True | False,
        'xps_files': ['/path1', '/path2', ...],   # all found paths (for upload)
        'message': '...'
      }
    """
    found   = detect_osteo_xps(xps_dir, scan_date, mrn=mrn)
    missing = [lbl for lbl in XPS_LABELS if lbl not in found]
    # Ready as long as at least one XPS is found — some patients only have
    # a spine scan (no hip order), so we must not block on missing femur files.
    ready   = len(found) > 0

    human = {'spine': 'Spine', 'left_femur': 'Left Femur', 'right_femur': 'Right Femur'}
    if not found:
        msg = (
            "No XPS files found for this patient.\n\n"
            "In GE Lunar: open the scan → File → Save As → XPS Document\n"
            f"Save to:  {xps_dir or config.XPS_WATCH_DIR}\n\n"
            "Then click ⟳ Refresh."
        )
    elif missing:
        names = ', '.join(human[m] for m in missing)
        msg = f"Found: {', '.join(human[f] for f in found)}. Not found: {names} (may not have been ordered — OK to proceed)."
    else:
        msg = "All XPS files found. Ready to upload."

    return {
        'found':     found,
        'missing':   missing,
        'ready':     ready,
        'xps_files': list(found.values()),   # flat list for upload loop
        'message':   msg,
    }


def clear_xps_watch_folder(xps_dir: Optional[str] = None,
                           paths_to_delete: Optional[list] = None) -> int:
    """
    Delete XPS files from the watch folder after a successful upload.
    If *paths_to_delete* is given, only those files are removed.
    Otherwise ALL .xps files in the folder are removed.
    Returns the number of files deleted.
    """
    watch = Path(xps_dir or config.XPS_WATCH_DIR)
    targets = (
        [Path(p) for p in paths_to_delete]
        if paths_to_delete
        else list(watch.glob('*.xps'))
    )
    deleted = 0
    for p in targets:
        try:
            p.unlink()
            log.info("Deleted %s", p.name)
            deleted += 1
        except Exception as e:
            log.warning("Could not delete %s: %s", p.name, e)
    return deleted


# ─── MDB snapshot ─────────────────────────────────────────────────────────────

def _serial(obj):
    if isinstance(obj, datetime):
        return obj.strftime('%Y-%m-%d %H:%M:%S')
    if isinstance(obj, date):
        return obj.isoformat()
    raise TypeError(f"Not JSON-serialisable: {type(obj)}")


def get_sessions_for_mrn(mrn: str) -> list[dict]:
    """Return all scan sessions for a patient from MDB, newest first."""
    return list_patient_sessions(config.MDB_PATH, mrn)


def build_raw_osteo_json(mrn: str, scan_index: int = 0, scan_date: str = None) -> dict:
    """
    Load the patient + OSTEO (spine/hip) session from MDB.

    Scoped strictly to osteo sessions (mdb_scan_type='osteo') across ALL
    pat_handles for this MRN.  Combined-scan patients (who also have a
    total-body scan) are handled correctly — total-body sessions are
    excluded so their composition data never bleeds into the osteo raw_json.

    If scan_date is provided (ISO format YYYY-MM-DD or full ISO), selects that specific date.
    Otherwise uses scan_index (default 0 = most recent).

    Raises RuntimeError if the patient or an osteo session is not found.
    """
    from parse_mdb import MdbParser

    parser = MdbParser(config.MDB_PATH)

    # Collect osteo sessions across ALL pat_handles for this MRN.
    # Combined-scan patients can have separate pat_handles per scan type,
    # or both types under the same handle — both cases are handled here.
    pat_sessions: list[tuple[dict, dict]] = []
    for ph, row in parser._patients.items():
        if row.get('patient_id', '').strip() != mrn:
            continue
        pat = parser._parse_patient(row)
        for sess in parser.get_scan_sessions(ph):
            if sess.get('mdb_scan_type') == 'osteo':
                pat_sessions.append((pat, sess))

    if not pat_sessions:
        raise RuntimeError(
            f"Patient MRN '{mrn}' has no osteo scan sessions in MDB.\n"
            "Check that the spine/femur scan was performed and analysed in GE Lunar."
        )

    # Newest osteo session first
    pat_sessions.sort(
        key=lambda x: x[1].get('scan_date') or datetime.min, reverse=True
    )

    # If scan_date is specified, find the matching session
    if scan_date:
        target_date_str = scan_date[:10]  # Extract YYYY-MM-DD
        for pat, sess in pat_sessions:
            sess_date_str = str(sess.get('scan_date', ''))[:10]
            if sess_date_str == target_date_str:
                # Build structured dict like the normal return
                return {
                    'patient': {
                        'pat_handle':  pat['pat_handle'],
                        'patient_id':  pat['patient_id'],
                        'mrn':         mrn,
                        'name':        pat.get('name', ''),
                        'title':       pat.get('title', ''),
                        'dob':         pat['dob'].isoformat() if pat.get('dob') else '',
                        'gender':      pat.get('gender', 'Female'),
                        'ethnicity':   pat.get('ethnicity', ''),
                        'height_cm':   pat.get('height_cm') or 0,
                        'weight_kg':   pat.get('weight_kg') or 0,
                        'bmi':         pat.get('bmi') or 0,
                        'physician':   pat.get('physician', ''),
                    },
                    'session': {
                        'scan_date':      sess.get('scan_date', ''),
                        'scanner_serial': sess.get('scanner_serial') or config.SCANNER_ID,
                        'software':       sess.get('software') or config.SOFTWARE,
                        'ntx_filename':   sess.get('ntx_filename'),
                        'spine':                 sess.get('spine', {}),
                        'left_femur':            sess.get('left_femur', {}),
                        'right_femur':           sess.get('right_femur', {}),
                        'estimated_composition': sess.get('estimated_composition', {}),
                    }
                }
        raise RuntimeError(
            f"No osteo scan found for MRN '{mrn}' on date {target_date_str}.\n"
            f"Available dates: {', '.join(str(s[1].get('scan_date', ''))[:10] for s in pat_sessions)}"
        )

    if scan_index >= len(pat_sessions):
        raise RuntimeError(
            f"scan_index {scan_index} out of range — "
            f"patient has {len(pat_sessions)} osteo session(s)."
        )

    pat, sess = pat_sessions[scan_index]

    return {
        'patient': {
            'pat_handle':  pat['pat_handle'],
            'patient_id':  pat['patient_id'],
            'mrn':         mrn,
            'name':        pat.get('name', ''),
            'title':       pat.get('title', ''),
            'dob':         pat['dob'].isoformat() if pat.get('dob') else '',
            'gender':      pat.get('gender', 'Female'),
            'ethnicity':   pat.get('ethnicity', ''),
            'height_cm':   pat.get('height_cm') or 0,
            'weight_kg':   pat.get('weight_kg') or 0,
            'bmi':         pat.get('bmi') or 0,
            'physician':   pat.get('physician', ''),
        },
        'session': {
            'scan_date':      sess.get('scan_date', ''),
            'scanner_serial': sess.get('scanner_serial') or config.SCANNER_ID,
            'software':       sess.get('software') or config.SOFTWARE,
            'ntx_filename':   sess.get('ntx_filename'),
            'spine':                 sess.get('spine', {}),
            'left_femur':            sess.get('left_femur', {}),
            'right_femur':           sess.get('right_femur', {}),
            'estimated_composition': sess.get('estimated_composition', {}),
        },
    }


# ─── Image extraction ─────────────────────────────────────────────────────────

def extract_images(xps_map: dict[str, str],
                   notify=None) -> dict[str, bytes]:
    """
    Extract PNG images from the XPS files.
    Returns {label: png_bytes} for each label in xps_map.
    Never raises — logs warnings on partial failure.
    """
    from PIL import Image as _PILImage
    _notify = notify or (lambda m: log.info(m))

    images: dict[str, bytes] = {}
    raw = extract_osteo_images(
        spine_xps       = xps_map.get('spine', ''),
        left_femur_xps  = xps_map.get('left_femur', ''),
        right_femur_xps = xps_map.get('right_femur', ''),
    )

    label_to_filename = {
        'spine':       'img_spine.png',
        'left_femur':  'img_left_femur.png',
        'right_femur': 'img_right_femur.png',
    }

    for label, img in raw.items():
        try:
            buf = io.BytesIO()
            img.save(buf, 'PNG', optimize=True)
            images[label] = buf.getvalue()
            kb = len(images[label]) // 1024
            msg = f"  {label_to_filename[label]} ({kb} KB)"
            log.info("Image extracted: %s", msg.strip())
            _notify(msg)
        except Exception as e:
            log.warning("Failed to encode %s image: %s", label, e)

    if not images:
        log.warning("No scan images extracted from XPS — check debug_xps.py output")
        _notify("  Warning: no scan images could be extracted from XPS files.")

    # ── Overlay pages via mutool (ROI boxes baked in) ────────────────────────
    _notify("  Rendering overlay pages…")
    overlay_map = {
        'spine_overlay':       'img_spine_overlay.png',
        'left_femur_overlay':  'img_left_femur_overlay.png',
        'right_femur_overlay': 'img_right_femur_overlay.png',
    }
    try:
        overlays = render_osteo_overlay_pages(
            spine_xps       = xps_map.get('spine', ''),
            left_femur_xps  = xps_map.get('left_femur', ''),
            right_femur_xps = xps_map.get('right_femur', ''),
        )
        for key, fname in overlay_map.items():
            if key in overlays:
                images[fname] = overlays[key]
                kb = len(overlays[key]) // 1024
                _notify(f"  {fname} ({kb} KB)")
    except Exception as e:
        log.warning("Overlay rendering failed: %s", e)
        _notify(f"  Warning: overlay rendering failed — {e}")

    return images


# ─── Main upload ──────────────────────────────────────────────────────────────

def upload_osteo_scan(mrn: str,
                      xps_map: dict[str, str],
                      progress_cb=None,
                      scan_index: int = 0,
                      scan_date: str = None) -> dict:
    """
    Full osteo upload for one patient:
      1. Read MDB → raw_osteo.json
      2. Extract PNG images from XPS
      3. Upload JSON + PNGs + raw XPS bytes to Supabase Storage
      4. Upsert patient + scan rows in Supabase DB
      5. Return upload result dict

    progress_cb(message: str) is called with status strings.
    scan_date: ISO date string (YYYY-MM-DD or full ISO) to select specific scan; if None, uses most recent
    Raises on fatal errors (MDB not found, Supabase unreachable, etc.).
    """
    from sync_supabase import upload_osteo_raw

    notify = progress_cb or (lambda m: log.info(m))

    # 1. MDB data
    notify(f"Reading MDB for MRN {mrn}…")
    raw_data = build_raw_osteo_json(mrn, scan_index=scan_index, scan_date=scan_date)
    raw_json_bytes = json.dumps(raw_data, indent=2, default=_serial).encode()

    # 2. Images
    notify("Extracting scan images from XPS…")
    images = extract_images(xps_map, notify=notify)

    # 3. Raw XPS bytes (for reprocessing)
    xps_bytes: dict[str, bytes] = {}
    for label, path in xps_map.items():
        p = Path(path)
        notify(f"Reading {p.name}…")
        xps_bytes[p.name] = p.read_bytes()

    # 4. Upload
    notify("Uploading to Supabase…")
    result = upload_osteo_raw(
        mrn          = mrn,
        raw_json     = raw_json_bytes,
        xps_files    = xps_bytes,
        png_images   = images,
        patient_data = raw_data['patient'],
        session_data = raw_data['session'],
    )

    puuid = result.get('patient_uuid')
    suuid = result.get('scan_uuid')
    db_ok = bool(puuid and suuid)
    notify(
        f"✓ Done — {len(xps_bytes)} XPS + {len(images)} PNG(s) uploaded.\n"
        f"  Storage: {result.get('storage_prefix')}\n"
        f"  DB: {'patient=' + puuid[:8] + '… scan=' + suuid[:8] + '…' if db_ok else 'WARNING — DB rows not confirmed'}"
    )
    return result


def upload_osteo_trend_scan(mrn: str,
                            archive_mdb_path: str,
                            progress_cb=None,
                            scan_index: int = 0) -> dict:
    """
    Upload osteo trend (archive MDB only, no XPS/images):
      1. Read MDB snapshot from archive
      2. Build raw_json (same format as regular scans)
      3. Call upload_osteo_raw with empty xps_files and png_images
      4. Upsert patient + scan rows with scan_type='osteo_trend'
    """
    from sync_supabase import upload_osteo_raw
    from collect import mdb_snapshot

    notify = progress_cb or (lambda m: log.info(m))

    # 1. Read archive MDB
    notify(f"Reading archive MDB for MRN {mrn}…")
    mdb_snap = mdb_snapshot(mrn, mdb_path=archive_mdb_path)

    # Validate patient has osteo scan in archive
    parser = MdbParser(archive_mdb_path)
    pat_handles = [
        ph for ph, row in parser._patients.items()
        if row.get('patient_id', '').strip() == str(mrn)
    ]
    if not pat_handles:
        raise RuntimeError(f'Patient {mrn} not found in archive MDB')

    sessions = parser.get_scan_sessions(pat_handles[0])
    osteo_sessions = [s for s in sessions if s.get('mdb_scan_type') == 'osteo']
    if not osteo_sessions:
        raise RuntimeError(f'Patient {mrn} has no osteo scan in archive')

    # 2. Extract patient and session from snapshot for raw_json structure
    first_exam = (mdb_snap.get('exams') or [{}])[0]
    patient_row = list(mdb_snap.get('patients', {}).values())[0] if mdb_snap.get('patients') else {}

    # Build raw_json with {patient, session} structure (same as regular scans) so it can be rendered as history
    raw_data = {
        'patient': {
            'pat_handle':  patient_row.get('pat_handle', f"mrn_{mrn}"),
            'patient_id':  mrn,
            'mrn':         mrn,
            'name':        patient_row.get('name', ''),
            'title':       patient_row.get('title', ''),
            'dob':         patient_row.get('dob', '').isoformat() if isinstance(patient_row.get('dob'), datetime) else patient_row.get('dob', ''),
            'gender':      patient_row.get('gender', 'Female'),
            'ethnicity':   patient_row.get('ethnicity', ''),
            'height_cm':   patient_row.get('height_cm') or 0,
            'weight_kg':   patient_row.get('weight_kg') or 0,
            'bmi':         patient_row.get('bmi') or 0,
            'physician':   patient_row.get('physician', ''),
        },
        'session': {
            'scan_date':      first_exam.get('_acq_dt', ''),
            'scanner_serial': first_exam.get('scanner_id') or config.SCANNER_ID,
            'software':       first_exam.get('software') or config.SOFTWARE,
            'ntx_filename':   first_exam.get('filename'),
            'spine':          mdb_snap.get('spine', {}),
            'left_femur':     mdb_snap.get('left_femur', {}),
            'right_femur':    mdb_snap.get('right_femur', {}),
            'estimated_composition': mdb_snap.get('estimated_composition', {}),
        }
    }
    raw_json_bytes = json.dumps(raw_data, indent=2, default=_serial).encode()

    patient_data = {
        'patient_id': mrn,
        'name':       patient_row.get('name', ''),
        'title':      patient_row.get('title', ''),
        'gender':     patient_row.get('gender', 'M'),
        'dob':        patient_row.get('dob'),
        'height_cm':  patient_row.get('height_cm'),
        'weight_kg':  patient_row.get('weight_kg'),
        'ethnicity':  patient_row.get('ethnicity', ''),
        'physician':  patient_row.get('physician', ''),
    }

    session_data = {
        'scan_type': 'osteo_trend',
        'scan_date': first_exam.get('_acq_dt'),
        'scanner_serial': first_exam.get('scanner_id'),
    }

    # 4. Upload to Supabase (empty XPS files and images)
    notify("Uploading trend to Supabase…")
    result = upload_osteo_raw(
        mrn          = mrn,
        raw_json     = raw_json_bytes,
        xps_files    = {},  # No XPS files for trends
        png_images   = {},  # No images for trends
        patient_data = None,  # Archive patient already exists in DB; skip upsert
        session_data = session_data,
        scan_type    = 'osteo_trend',  # Suffix for trends
    )

    puuid = result.get('patient_uuid')
    suuid = result.get('scan_uuid')
    db_ok = bool(puuid and suuid)
    notify(
        f"✓ Trend uploaded.\n"
        f"  DB: {'patient=' + puuid[:8] + '… scan=' + suuid[:8] + '…' if db_ok else 'WARNING — DB rows not confirmed'}"
    )
    return result


# ─── Recent patient helper (for UI auto-load) ─────────────────────────────────

def get_patient_by_mrn(mrn: str) -> Optional[dict]:
    """
    Load patient info + XPS status for any MRN (not just the latest).
    Returns the same shape as get_latest_patient().
    """
    from parse_mdb import MdbParser
    try:
        parser = MdbParser(config.MDB_PATH)
    except Exception as e:
        log.error("Cannot open MDB: %s", e)
        return None

    patient = parser.find_patient(mrn)
    if not patient:
        return None

    sessions = parser.get_scan_sessions(patient['pat_handle'])
    if not sessions:
        return None

    latest = sessions[0]
    scan_dt = latest.get('scan_date')
    mdb_scan_type = latest.get('mdb_scan_type', 'osteo')
    # find_patient() returns {'name': full_name, 'title': salutation, ...}
    name = f"{patient.get('title', '')} {patient.get('name', '')}".strip()
    status = xps_status(scan_date=scan_dt, mrn=mrn)

    return {
        'mrn':           mrn,
        'name':          name,
        'scan_date':     scan_dt,
        'mdb_scan_type': mdb_scan_type,
        'xps_status':    status,
    }


def get_latest_patient() -> Optional[dict]:
    """
    Return the most recently scanned patient from the MDB (last 72 hrs),
    or None if the MDB is empty / unreachable.

    Returns:
      {'mrn': str, 'name': str, 'scan_date': datetime, 'xps_status': dict}
    """
    from parse_mdb import MdbParser
    from datetime import timedelta

    try:
        parser = MdbParser(config.MDB_PATH)
    except Exception as e:
        log.error("Cannot open MDB: %s", e)
        return None

    cutoff = datetime.now() - timedelta(hours=72)
    best_exam = None
    best_dt   = None

    for exam in parser._exams:
        acq = exam.get('_acq_dt')
        if not acq or acq < cutoff:
            continue
        if best_dt is None or acq > best_dt:
            best_dt   = acq
            best_exam = exam

    if not best_exam:
        return None

    pat_handle = best_exam.get('pat_handle', '')
    pat_row    = parser._patients.get(pat_handle)
    if not pat_row:
        return None

    mrn  = (pat_row.get('patient_id') or '').strip()
    # _patients stores raw MDB fields: last_name=salutation, first_name=full name
    name = f"{pat_row.get('last_name', '')} {pat_row.get('first_name', '')}".strip()

    # Pass mrn + scan_date so XPS matching is locked to this patient
    sessions = parser.get_scan_sessions(pat_handle)
    mdb_scan_type = sessions[0].get('mdb_scan_type', 'osteo') if sessions else 'osteo'
    status = xps_status(scan_date=best_dt, mrn=mrn)

    return {
        'mrn':           mrn,
        'name':          name,
        'scan_date':     best_dt,
        'mdb_scan_type': mdb_scan_type,
        'xps_status':    status,
    }


# ─── Self-test ────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import sys
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')

    mrn = sys.argv[1] if len(sys.argv) > 1 else None

    if not mrn:
        print("Usage: python collect_osteo.py <mrn>")
        print()
        print("Checking MDB for latest patient…")
        latest = get_latest_patient()
        if latest:
            print(f"  Latest: {latest['name']}  MRN={latest['mrn']}  scan={latest['scan_date']}")
            st = latest['xps_status']
            print(f"  XPS status: {'READY' if st['ready'] else 'NOT READY'}")
            for lbl, path in st['found'].items():
                print(f"    ✓ {lbl}: {path}")
            for lbl in st['missing']:
                print(f"    ✗ {lbl}: NOT FOUND")
        else:
            print("  No recent patients found.")
        sys.exit(0)

    print(f"MRN: {mrn}")
    print(f"MDB: {config.MDB_PATH}")
    print(f"XPS: {config.XPS_WATCH_DIR}")
    print()

    st = xps_status(mrn)
    print(f"XPS status: {'READY' if st['ready'] else 'NOT READY'}")
    for lbl, path in st['found'].items():
        print(f"  ✓ {lbl}: {Path(path).name}")
    for lbl in st['missing']:
        print(f"  ✗ {lbl}: NOT FOUND")

    if not st['ready']:
        print()
        print(st['message'])
        sys.exit(1)

    print()
    upload_osteo_scan(mrn, st['found'], progress_cb=print)
