"""
Total-body DEXA data collector.

Mirrors collect_osteo.py but for total-body scans (composition + bone).
Detects XPS files, parses them, extracts colourised images, and uploads
everything to Supabase Storage + DB (scan_type='total_body').

Storage layout:
  raw-totalbody/{mrn}/{timestamp}/
    raw_totalbody.json          — mdb_snapshot + xps_bone + xps_composition
    img_fat_lean.png            — fat=pink / lean=cyan silhouette
    img_fat_gradient.png        — fat heat-map silhouette
    img_bone.png                — bone-density chart from bone XPS
    img_composite.png           — full-body bone-mode silhouette
    {xps-name}.xps              — raw XPS bytes (for reprocessing)
"""

import io
import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import config
from parse_xps import detect_xps_type
from parse_xps_totalbody import (
    parse_totalbody_bone,
    parse_totalbody_composition,
    extract_totalbody_images,
    colorize_dexa_silhouette,
)
from collect import mdb_snapshot          # reuse existing MDB snapshot builder

log = logging.getLogger(__name__)


# ─── XPS detection ────────────────────────────────────────────────────────────

def detect_totalbody_xps(
    mrn: Optional[str] = None,
    xps_dir: Optional[str] = None,
    scan_date: Optional[datetime] = None,
) -> dict[str, str]:
    """
    Find bone + composition XPS files for a total-body patient.

    Returns: {'bone': '/abs/path.xps', 'composition': '/abs/path.xps'}
    Keys are omitted when the corresponding file is not found.
    """
    watch = Path(xps_dir or config.XPS_WATCH_DIR)
    if not watch.exists():
        log.warning("XPS watch dir does not exist: %s", watch)
        return {}

    all_xps = sorted(watch.glob('*.xps'), key=lambda p: p.stat().st_mtime, reverse=True)
    if not all_xps:
        return {}

    # MRN filter — mandatory when mrn is known
    if mrn:
        mrn_xps = [p for p in all_xps if mrn in p.name]
        if mrn_xps:
            log.info("TB XPS filter: %d file(s) with MRN %s", len(mrn_xps), mrn)
            all_xps = mrn_xps
        else:
            log.warning("No XPS files contain MRN %s — aborting", mrn)
            return {}

    # Date / recency filter
    if scan_date:
        target = scan_date.date() if isinstance(scan_date, datetime) else scan_date
        candidates = [p for p in all_xps
                      if datetime.fromtimestamp(p.stat().st_mtime).date() == target]
        if not candidates:
            log.info("No XPS on %s — widening to 7 days", target)
            cutoff = datetime.now() - timedelta(days=7)
            candidates = [p for p in all_xps
                          if datetime.fromtimestamp(p.stat().st_mtime) >= cutoff]
    else:
        cutoff = datetime.now() - timedelta(days=7)
        candidates = [p for p in all_xps
                      if datetime.fromtimestamp(p.stat().st_mtime) >= cutoff]

    if not candidates:
        candidates = all_xps[:5]

    result: dict[str, str] = {}
    for xps_path in candidates:
        abs_path = str(xps_path.resolve())
        xtype = detect_xps_type(abs_path)
        mtime = datetime.fromtimestamp(xps_path.stat().st_mtime).strftime('%H:%M')
        if xtype == 'totalbody_bone' and 'bone' not in result:
            result['bone'] = abs_path
            log.info("  %s → bone  (%s)", xps_path.name, mtime)
        elif xtype in ('totalbody_composition', 'totalbody_narrative') and 'composition' not in result:
            result['composition'] = abs_path
            log.info("  %s → composition  (%s)", xps_path.name, mtime)

    return result


def tb_xps_status(
    mrn: Optional[str] = None,
    xps_dir: Optional[str] = None,
    scan_date: Optional[datetime] = None,
) -> dict:
    """Return status dict for UI (mirrors collect_osteo.xps_status)."""
    found   = detect_totalbody_xps(mrn, xps_dir, scan_date)
    missing = [k for k in ('bone', 'composition') if k not in found]
    ready   = len(found) > 0            # any XPS found is enough to proceed

    human = {'bone': 'Bone Density XPS', 'composition': 'Composition XPS'}
    if not found:
        msg = (
            "No total-body XPS files found.\n\n"
            "In GE Lunar: open the total-body scan → File → Save As → XPS Document\n"
            f"Save to:  {xps_dir or config.XPS_WATCH_DIR}\n\n"
            "Then click ⟳ Refresh."
        )
    elif missing:
        names = ', '.join(human[m] for m in missing)
        msg = (
            f"Found: {', '.join(human[f] for f in found)}. "
            f"Not found: {names} (proceed if composition XPS unavailable)."
        )
    else:
        msg = "Both total-body XPS files found. Ready to upload."

    return {
        'found':     found,
        'missing':   missing,
        'ready':     ready,
        'xps_files': list(found.values()),
        'message':   msg,
    }


# ─── Data building ────────────────────────────────────────────────────────────

def _serial(obj):
    if isinstance(obj, datetime):
        return obj.strftime('%Y-%m-%d %H:%M:%S')
    if isinstance(obj, date):
        return obj.isoformat()
    raise TypeError(f"Not JSON-serialisable: {type(obj)}")


def build_raw_totalbody_json(mrn: str, xps_map: dict[str, str]) -> dict:
    """
    Build the raw_json payload expected by computeReportData() in bmd-compute.js.

    Shape:
      {
        'mdb_snapshot':    { patients, exams, composition, densitometry, … },
        'xps_bone':        parse_totalbody_bone() result  | None,
        'xps_composition': parse_totalbody_composition() result | None,
      }
    """
    log.info("Building MDB snapshot for MRN %s", mrn)
    snap = mdb_snapshot(mrn)

    xps_bone = None
    xps_comp = None

    bone_path = xps_map.get('bone', '')
    comp_path = xps_map.get('composition', '')

    if bone_path:
        try:
            xps_bone = parse_totalbody_bone(bone_path)
            log.info("Parsed bone XPS: %d regions", len(xps_bone.get('regions', {})))
        except Exception as e:
            log.warning("Bone XPS parse failed: %s", e)

    if comp_path:
        try:
            xps_comp = parse_totalbody_composition(comp_path)
            log.info("Parsed composition XPS: fat_pct=%s", xps_comp.get('fat_pct'))
        except Exception as e:
            log.warning("Composition XPS parse failed: %s", e)

    return {
        'mdb_snapshot':    snap,
        'xps_bone':        xps_bone,
        'xps_composition': xps_comp,
    }


# ─── Image extraction ─────────────────────────────────────────────────────────

def extract_tb_images(xps_map: dict[str, str], notify=None) -> dict[str, bytes]:
    """
    Extract and colourise total-body PNG images from XPS files.
    Returns {filename: png_bytes}.
    """
    _notify = notify or (lambda m: log.info(m))
    bone_path = xps_map.get('bone', '')
    comp_path = xps_map.get('composition', '') or None
    images: dict[str, bytes] = {}

    try:
        raw = extract_totalbody_images(bone_path, comp_path)
    except Exception as e:
        log.warning("extract_totalbody_images failed: %s", e)
        _notify(f"  Warning: image extraction failed — {e}")
        return images

    body_sil = raw.get('body_silhouette')
    bmd_chart = raw.get('bmd_chart')

    if body_sil:
        for mode, fname in [
            ('fat_lean',     'img_fat_lean.png'),
            ('fat_gradient', 'img_fat_gradient.png'),
        ]:
            try:
                img = colorize_dexa_silhouette(body_sil, mode=mode)
                buf = io.BytesIO()
                img.save(buf, 'PNG', optimize=True)
                images[fname] = buf.getvalue()
                kb = len(images[fname]) // 1024
                _notify(f"  {fname} ({kb} KB)")
            except Exception as e:
                log.warning("Colourise %s failed: %s", mode, e)

        # Bone-mode silhouette for composite slot
        try:
            img = colorize_dexa_silhouette(body_sil, mode='bone')
            buf = io.BytesIO()
            img.save(buf, 'PNG', optimize=True)
            images['img_composite.png'] = buf.getvalue()
            _notify(f"  img_composite.png ({len(images['img_composite.png']) // 1024} KB)")
        except Exception as e:
            log.warning("Bone-mode silhouette failed: %s", e)

    if bmd_chart:
        try:
            buf = io.BytesIO()
            bmd_chart.convert('RGB').save(buf, 'PNG', optimize=True)
            images['img_bone.png'] = buf.getvalue()
            _notify(f"  img_bone.png ({len(images['img_bone.png']) // 1024} KB)")
        except Exception as e:
            log.warning("BMD chart save failed: %s", e)

    if not images:
        _notify("  Warning: no images could be extracted from XPS.")

    return images


# ─── Patient info for DB upsert ───────────────────────────────────────────────

def _ge_date_to_iso(s: str) -> str:
    """Convert GE Lunar MM-DD-YYYY (US format) to ISO YYYY-MM-DD; return original if unrecognised."""
    import re
    m = re.match(r'^(\d{2})-(\d{2})-(\d{4})$', s or '')
    return f"{m.group(3)}-{m.group(1)}-{m.group(2)}" if m else s


def _patient_from_snapshot(mrn: str, snap: dict, xps_bone=None, xps_comp=None) -> tuple[dict, dict]:
    """Extract patient_data + session_data dicts for upload_totalbody_raw."""
    pat_handles = list(snap.get('patients', {}).keys())
    pat_row = snap['patients'][pat_handles[0]] if pat_handles else {}
    exams   = snap.get('exams', [])
    exam    = exams[0] if exams else {}

    xps_pat = (xps_bone or {}).get('patient') or (xps_comp or {}).get('patient') or {}

    patient_data = {
        'pat_handle':  pat_handles[0] if pat_handles else f"mrn_{mrn}",
        'patient_id':  mrn,
        'name':        xps_pat.get('name') or pat_row.get('first_name', ''),
        'title':       xps_pat.get('title') or pat_row.get('last_name', ''),
        'dob':         pat_row.get('dob') or '',
        'gender':      xps_pat.get('gender') or pat_row.get('gender', ''),
        'height_cm':   xps_pat.get('height_cm') or float(pat_row.get('height') or 0),
        'weight_kg':   xps_pat.get('weight_kg') or float(pat_row.get('weight') or 0),
        'physician':   xps_pat.get('physician') or pat_row.get('physician', ''),
    }
    scan_dt = _ge_date_to_iso(xps_pat.get('scan_date_str', '')) or exam.get('_acq_dt', '')
    session_data = {
        'scan_date':      scan_dt,
        'scanner_serial': exam.get('scanner_id') or config.SCANNER_ID,
        'software':       exam.get('acquisition_version') or config.SOFTWARE,
    }
    return patient_data, session_data


# ─── Main upload ──────────────────────────────────────────────────────────────

def upload_totalbody_scan(
    mrn: str,
    xps_map: dict[str, str],
    progress_cb=None,
) -> dict:
    """
    Full total-body upload for one patient:
      1. Build MDB snapshot + parse XPS → raw_json
      2. Extract colourised PNG images
      3. Upload JSON + PNGs + raw XPS to Supabase Storage
      4. Upsert patient + scan rows in Supabase DB
    """
    from sync_supabase import upload_totalbody_raw

    notify = progress_cb or (lambda m: log.info(m))

    # 1. MDB + XPS data
    notify(f"Reading MDB + XPS for MRN {mrn}…")
    raw_data = build_raw_totalbody_json(mrn, xps_map)
    raw_json_bytes = json.dumps(raw_data, indent=2, default=_serial).encode()

    # 2. Images
    notify("Extracting scan images…")
    images = extract_tb_images(xps_map, notify=notify)

    # 3. Raw XPS bytes
    xps_bytes: dict[str, bytes] = {}
    for label, path in xps_map.items():
        p = Path(path)
        notify(f"Reading {p.name}…")
        xps_bytes[p.name] = p.read_bytes()

    # 4. Patient/session info for DB
    xps_bone = raw_data.get('xps_bone')
    xps_comp = raw_data.get('xps_composition')
    patient_data, session_data = _patient_from_snapshot(
        mrn, raw_data['mdb_snapshot'], xps_bone, xps_comp,
    )

    # 5. Upload
    notify("Uploading to Supabase…")
    result = upload_totalbody_raw(
        mrn          = mrn,
        raw_json     = raw_json_bytes,
        xps_files    = xps_bytes,
        png_images   = images,
        patient_data = patient_data,
        session_data = session_data,
        notify       = notify,
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
