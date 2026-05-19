"""
Full pipeline: MDB scan_handle → PDF → Supabase.

Orchestrates parse_mdb → parse_xps → render_pdf → sync_supabase.
"""

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

import config
from parse_mdb import MdbParser
from parse_xps import parse_xps_bmd, extract_scan_images, reconcile, detect_xps_type
from parse_xps_totalbody import (
    parse_totalbody_bone, parse_totalbody_composition, extract_totalbody_images,
)
from render_pdf_totalbody import render_totalbody_pdf
from render_pdf import render_pdf
try:
    from sync_supabase import sync_scan as _sync_scan
    _SUPABASE_AVAILABLE = True
except ImportError:
    _SUPABASE_AVAILABLE = False
    _sync_scan = None

log = logging.getLogger(__name__)

_mdb_parser: Optional[MdbParser] = None


def get_parser() -> MdbParser:
    """Return a cached MDB parser (reload on each watcher cycle if desired)."""
    global _mdb_parser
    if _mdb_parser is None:
        _mdb_parser = MdbParser(config.MDB_PATH)
    return _mdb_parser


def reload_parser():
    global _mdb_parser
    _mdb_parser = None


def _find_xps(patient_id: str, scan_date: Optional[datetime]) -> Optional[str]:
    """Search XPS_WATCH_DIR for an XPS file matching this patient."""
    watch = Path(config.XPS_WATCH_DIR)
    # Exact match: {patient_id}.xps
    candidate = watch / f"{patient_id}.xps"
    if candidate.exists():
        return str(candidate)
    # Fallback: any XPS containing the patient_id
    for f in watch.glob('*.xps'):
        if patient_id in f.name:
            return str(f)
    # Most recent XPS if scan_date is today
    if scan_date and scan_date.date() == datetime.now().date():
        xps_files = sorted(watch.glob('*.xps'), key=lambda p: p.stat().st_mtime)
        if xps_files:
            return str(xps_files[-1])
    return None


def build_report_data(patient: dict, session: dict, merged: dict,
                      scan_images: dict) -> dict:
    """Assemble the report_data dict consumed by render_pdf.render_pdf()."""
    dob = patient.get('dob')
    scan_date = session.get('scan_date')
    age = None
    if dob and scan_date:
        age = round((scan_date.date() - dob).days / 365.25, 1)

    patient_for_pdf = {
        **patient,
        'pid':        patient.get('patient_id', ''),
        'age':        age or patient.get('age', ''),
        'scan_date':  scan_date.strftime('%d-%m-%Y') if scan_date else '',
        'scan_time':  scan_date.strftime('%H:%M:%S') if scan_date else '',
        'scanner':    session.get('scanner_serial') or config.SCANNER_ID,
        'software':   session.get('software') or config.SOFTWARE,
    }

    return {
        'patient':      patient_for_pdf,
        'spine':        merged.get('spine', {}),
        'left_femur':   merged.get('left_femur', {}),
        'right_femur':  merged.get('right_femur', {}),
        'scan_images':  scan_images,
    }


def run_pipeline(scan_handle: str, upload: bool = True,
                 xps_path: Optional[str] = None) -> Optional[bytes]:
    """
    Full pipeline for one scan_handle.

    1. Find patient + session in MDB
    2. Find + parse XPS file  (use xps_path if supplied, else search by patient_id)
    3. Reconcile XPS + MDB data
    4. Render PDF
    5. Optionally sync to Supabase
    Returns PDF bytes (or None on error).
    """
    log.info("Pipeline start: scan_handle=%s", scan_handle)
    try:
        parser = get_parser()

        # ── 1. Find session in MDB ──────────────────────────────────
        all_exams = [e for e in parser._exams
                     if e.get('scan_handle') == scan_handle]
        if not all_exams:
            log.error("scan_handle %s not found in MDB", scan_handle)
            return None

        pat_handle = all_exams[0]['pat_handle']
        patient_row = parser._patients.get(pat_handle)
        if not patient_row:
            log.error("Patient %s not found", pat_handle)
            return None
        patient = parser._parse_patient(patient_row)

        session = parser._parse_session(scan_handle, all_exams)
        if not session:
            log.error("Could not parse session for %s", scan_handle)
            return None

        log.info("Patient: %s  Date: %s", patient['name'], session.get('scan_date'))

        # ── 2. Locate and parse XPS ─────────────────────────────────
        pid = patient.get('patient_id', '')
        if xps_path is None:
            xps_path = _find_xps(pid, session.get('scan_date'))
        xps_data = {}
        scan_images = {}
        if xps_path:
            log.info("XPS: %s", xps_path)
            try:
                xps_data = parse_xps_bmd(xps_path)
                scan_images = extract_scan_images(xps_path)
                session['xps_filename'] = Path(xps_path).name
                # Merge XPS patient fields
                xps_pat = xps_data.get('patient', {})
                if xps_pat.get('height_cm'):
                    patient['height_cm'] = xps_pat['height_cm']
                if xps_pat.get('weight_kg'):
                    patient['weight_kg'] = xps_pat['weight_kg']
                h, w = patient.get('height_cm'), patient.get('weight_kg')
                if h and w:
                    patient['bmi'] = round(w / (h / 100) ** 2, 1)
            except Exception as e:
                log.warning("XPS parse failed (%s) — proceeding with MDB only", e)
        else:
            log.warning("No XPS found for patient %s", pid)

        # ── 3. Reconcile ─────────────────────────────────────────────
        merged = reconcile(xps_data, session)

        # ── 4. Build report_data ──────────────────────────────────────
        report_data = build_report_data(patient, session, merged, scan_images)

        # ── 5. Render PDF ─────────────────────────────────────────────
        pdf_bytes = render_pdf(report_data)
        log.info("PDF rendered: %d bytes", len(pdf_bytes))

        # Save local copy
        out_dir = Path(config.OUTPUT_PDF_DIR)
        out_dir.mkdir(parents=True, exist_ok=True)
        sd = session.get('scan_date')
        fname = f"{pid}_{sd.strftime('%Y%m%d') if sd else 'nodate'}.pdf"
        (out_dir / fname).write_bytes(pdf_bytes)
        log.info("Saved: %s", out_dir / fname)

        # ── 6. Sync to Supabase ───────────────────────────────────────
        if upload and _SUPABASE_AVAILABLE and _sync_scan:
            try:
                _sync_scan(patient, session, merged, pdf_bytes)
            except Exception as e:
                log.error("Supabase sync failed: %s", e)
        elif upload and not _SUPABASE_AVAILABLE:
            log.warning("supabase package not installed — skipping upload")

        return pdf_bytes

    except Exception as e:
        log.exception("Pipeline failed for %s: %s", scan_handle, e)
        return None


def run_pipeline_for_patient(patient_id: str, upload: bool = True) -> Optional[bytes]:
    """Run pipeline for a patient by clinic patient_id (latest scan)."""
    parser = get_parser()
    patient_row = None
    for p in parser._patients.values():
        if p.get('patient_id', '').strip() == patient_id.strip():
            patient_row = p
            break
    if not patient_row:
        log.error("Patient %s not found", patient_id)
        return None

    sessions = parser.get_scan_sessions(patient_row['pat_handle'])
    if not sessions:
        log.error("No sessions for patient %s", patient_id)
        return None

    return run_pipeline(sessions[0]['scan_handle'], upload=upload)


def run_pipeline_xps(xps_path: str, upload: bool = True) -> Optional[bytes]:
    """
    XPS-file-triggered entry point (used by the watcher).

    patient_id  = everything before the first '-' in the filename stem,
                  e.g. '20260323063-spine.xps' → '20260323063'

    Detects scan type from XPS content and dispatches:
      spine_femur          → full PDF pipeline
      totalbody_*          → Phase 2 (not yet implemented, skipped)
      unknown              → skipped with a warning
    """
    xps_file = Path(xps_path)
    patient_id = xps_file.stem.split('-')[0].strip()

    log.info("XPS trigger: %s  patient_id=%s", xps_file.name, patient_id)

    # ── Route from MDB — the single source of truth for scan type ────────────
    # XPS content detection is unreliable (spine-only looks like total-body-bone).
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
    log.info("MDB scan type for %s: %s", patient_id, mdb_scan_type)

    if mdb_scan_type == 'total_body':
        # Within total-body, still use XPS sub-type to split bone vs composition files.
        xps_type = detect_xps_type(xps_path)
        return _run_totalbody(xps_path, patient_id, xps_type, upload)

    return _run_spine_femur(xps_path, patient_id, upload)


def _run_totalbody(xps_path: str, patient_id: str, xps_type: str,
                   upload: bool) -> Optional[bytes]:
    """
    Build a total-body PDF from all available XPS files for this patient.

    Finds sibling XPS files in the same directory with the same patient_id prefix,
    detects each one's type, parses and combines them.
    """
    watch = Path(xps_path).parent
    siblings = list(watch.glob(f'{patient_id}*.xps')) + list(watch.glob(f'{patient_id}-*.xps'))
    siblings = sorted({str(p.resolve()) for p in siblings})

    log.info("Total-body pipeline: %d candidate XPS files for patient %s", len(siblings), patient_id)

    bone_xps = None
    comp_candidates: list[str] = []
    for p in siblings:
        try:
            t = detect_xps_type(p)
        except Exception:
            continue
        if t == 'totalbody_bone' and bone_xps is None:
            bone_xps = p
        elif t == 'totalbody_composition':
            comp_candidates.append(p)

    if bone_xps is None and xps_type == 'totalbody_bone':
        bone_xps = xps_path
    if xps_type == 'totalbody_composition' and xps_path not in comp_candidates:
        comp_candidates.append(xps_path)

    # Pick the composition XPS with the most parseable data
    comp_xps: Optional[str] = None
    best_score = -1
    for p in comp_candidates:
        try:
            d = parse_totalbody_composition(p)
            score = sum(1 for k in ('fat_pct', 'fat_g', 'lean_g', 'ag_ratio', 'bmi')
                        if d.get(k) is not None)
            if score > best_score:
                best_score = score
                comp_xps = p
        except Exception:
            continue

    log.info("bone_xps=%s  comp_xps=%s", bone_xps, comp_xps)

    # ── Parse data ─────────────────────────────────────────────────
    bone_data = {}
    comp_data = {}
    patient   = {}

    if bone_xps:
        try:
            bone_data = parse_totalbody_bone(bone_xps)
            patient   = bone_data.get('patient', {})
        except Exception as e:
            log.warning("parse_totalbody_bone failed: %s", e)

    if comp_xps:
        try:
            comp_data = parse_totalbody_composition(comp_xps)
            if not patient:
                patient = comp_data.get('patient', {})
        except Exception as e:
            log.warning("parse_totalbody_composition failed: %s", e)

    # ── MDB: patient demographics + regional composition ──────────────
    try:
        reload_parser()
        parser = get_parser()
        pat_row = next(
            (p for p in parser._patients.values()
             if p.get('patient_id', '').strip() == patient_id),
            None,
        )
        if pat_row:
            if not patient:
                patient = parser._parse_patient(pat_row)
            img_handle = parser.find_totalbody_img_handle(pat_row['pat_handle'])
            if img_handle:
                regions = parser.get_totalbody_regions(img_handle)
                if regions:
                    comp_data['regions'] = regions
                    log.info("MDB regional composition: %s", list(regions.keys()))
    except Exception as e:
        log.warning("MDB totalbody lookup failed: %s", e)

    # ── Extract scan images ────────────────────────────────────────
    scan_images = {}
    try:
        scan_images = extract_totalbody_images(
            bone_xps or xps_path,
            comp_xps,
        )
        log.info("Extracted total-body images: %s", list(scan_images.keys()))
    except Exception as e:
        log.warning("extract_totalbody_images failed: %s", e)

    # ── Render PDF ─────────────────────────────────────────────────
    report_data = {
        'patient':     patient,
        'bone':        bone_data,
        'composition': comp_data,
        'scan_images': scan_images,
    }
    try:
        pdf_bytes = render_totalbody_pdf(report_data)
        log.info("Total-body PDF rendered: %d bytes", len(pdf_bytes))
    except Exception as e:
        log.exception("render_totalbody_pdf failed: %s", e)
        return None

    # ── Save local copy ────────────────────────────────────────────
    out_dir  = Path(config.OUTPUT_PDF_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    scan_date = patient.get('scan_date') or datetime.now()
    date_str  = scan_date.strftime('%Y%m%d') if hasattr(scan_date, 'strftime') else 'nodate'
    fname     = f"{patient_id}_{date_str}_totalbody.pdf"
    (out_dir / fname).write_bytes(pdf_bytes)
    log.info("Saved: %s", out_dir / fname)

    # ── Supabase upload ────────────────────────────────────────────
    if upload and _SUPABASE_AVAILABLE and _sync_scan:
        try:
            session = {
                'scan_type':    'totalbody',
                'xps_filename': Path(xps_path).name,
                'scan_date':    scan_date,
            }
            _sync_scan(patient, session, {}, pdf_bytes)
        except Exception as e:
            log.error("Supabase sync failed: %s", e)
    elif upload and not _SUPABASE_AVAILABLE:
        log.warning("supabase package not installed — skipping upload")

    return pdf_bytes


def _run_spine_femur(xps_path: str, patient_id: str, upload: bool) -> Optional[bytes]:
    """Resolve MDB scan_handle for this patient + XPS, then run the standard pipeline."""
    reload_parser()
    parser = get_parser()

    # Find patient in MDB
    pat_row = next(
        (p for p in parser._patients.values()
         if p.get('patient_id', '').strip() == patient_id),
        None,
    )
    if not pat_row:
        log.error("Patient %s not found in MDB — cannot process %s", patient_id, xps_path)
        return None

    sessions = parser.get_scan_sessions(pat_row['pat_handle'])
    if not sessions:
        log.error("No MDB sessions for patient %s", patient_id)
        return None

    # Try to match by scan date embedded in XPS text; fall back to most recent session
    scan_handle = sessions[0]['scan_handle']
    try:
        from parse_xps import extract_xps_text, _group_lines, _line_text, _parse_patient_header
        glyphs = extract_xps_text(xps_path)
        lines  = _group_lines(glyphs)
        full   = '\n'.join(_line_text(l) for l in lines)
        xps_pat = _parse_patient_header(full)
        date_str = xps_pat.get('scan_date_str', '')
        if date_str:
            # enCORE formats: MM/DD/YYYY or DD/MM/YYYY — try both
            for fmt in ('%m/%d/%Y', '%d/%m/%Y', '%Y-%m-%d'):
                try:
                    xps_date = datetime.strptime(date_str, fmt).date()
                    for s in sessions:
                        if s.get('scan_date') and s['scan_date'].date() == xps_date:
                            scan_handle = s['scan_handle']
                            log.info("Matched MDB session by date %s → %s", xps_date, scan_handle)
                    break
                except ValueError:
                    continue
    except Exception as e:
        log.debug("Date-match skipped: %s", e)

    return run_pipeline(scan_handle, upload=upload, xps_path=xps_path)
