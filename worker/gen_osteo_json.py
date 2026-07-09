"""
Generate _raw_osteo.json + scan images for a patient from the MDB + XPS files.

Usage:
  python3 gen_osteo_json.py <patient_id> [mdb_path] [xps_dir] [out_dir]

XPS dir should contain files named {patient_id}-1.xps, -2.xps, etc.
The script auto-detects which XPS is spine vs left/right femur by reading text.
"""

import sys
import json
import logging
import os
from pathlib import Path
from datetime import date, datetime

sys.path.insert(0, str(Path(__file__).parent))
from parse_mdb import load_patient_session
from parse_xps import extract_osteo_images, extract_xps_text

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')

MDB_DEFAULT     = '/Users/pav/projects/bmd/machine-data/data-2026/lunar.mdb'
XPS_DIR_DEFAULT = '/Users/pav/projects/bmd/machine-data/data-2026'
OUT_DIR_DEFAULT = '/tmp/sdrc-reports'


def _serial(obj):
    if isinstance(obj, datetime):
        return obj.strftime('%Y-%m-%d %H:%M:%S')
    if isinstance(obj, date):
        return obj.isoformat()
    raise TypeError(f'Not serializable: {type(obj)}')


def _classify_xps(xps_path: str) -> str:
    """Return 'spine', 'left_femur', 'right_femur', 'left_forearm', 'right_forearm', or 'unknown'."""
    try:
        tokens = ' '.join(t for _, _, t in extract_xps_text(xps_path))
    except Exception:
        return 'unknown'
    has_spine    = any(x in tokens for x in ['Lumbar', 'Spine', 'lumbar', 'spine'])
    has_femur    = any(x in tokens for x in ['Femur', 'femur', 'Neck', 'Trochanter'])
    has_forearm  = any(x in tokens for x in ['Forearm', 'forearm', 'Radius', 'Ulna', 'radius', 'ulna'])
    has_left     = any(x in tokens for x in ['Left', 'left', 'LEFT'])
    has_right    = any(x in tokens for x in ['Right', 'right', 'RIGHT'])
    if has_spine and not has_femur and not has_forearm:
        return 'spine'
    if has_femur and not has_forearm and has_left and not has_right:
        return 'left_femur'
    if has_femur and not has_forearm and has_right and not has_left:
        return 'right_femur'
    if has_forearm and not has_femur and has_left and not has_right:
        return 'left_forearm'
    if has_forearm and not has_femur and has_right and not has_left:
        return 'right_forearm'
    return 'unknown'


def detect_xps_files(patient_id: str, xps_dir: str) -> dict[str, str]:
    """
    Scan xps_dir for XPS files and classify each.
    Searches for:
    - {patient_id}.xps (combined: spine, femur, etc.)
    - {patient_id}-N.xps (numbered: -1, -2, etc.)
    - {patient_id}-FOREARM*.xps (forearm-specific)
    Returns dict with keys like 'spine', 'left_femur', 'right_femur', 'left_forearm', 'right_forearm'
    """
    xps_dir = Path(xps_dir)
    mapping: dict[str, str] = {}

    # Start with combined file if it exists
    combined = xps_dir / f'{patient_id}.xps'
    if combined.exists():
        mapping['combined'] = str(combined)
        logging.info('Found combined XPS: %s', combined.name)

    # Then scan for numbered or site-specific files
    candidates = sorted(
        xps_dir.glob(f'{patient_id}-*.xps'),
        key=lambda p: (
            p.stem.split('-')[-1].isdigit(),  # put numbered files first
            int(p.stem.split('-')[-1]) if p.stem.split('-')[-1].isdigit() else 0
        )
    )

    for xps_path in candidates:
        label = _classify_xps(str(xps_path))
        if label != 'unknown' and label not in mapping:
            mapping[label] = str(xps_path)
            logging.info('Classified %s → %s', xps_path.name, label)

    return mapping


def main():
    patient_id = sys.argv[1] if len(sys.argv) > 1 else '20260430113'
    mdb_path   = sys.argv[2] if len(sys.argv) > 2 else MDB_DEFAULT
    xps_dir    = sys.argv[3] if len(sys.argv) > 3 else XPS_DIR_DEFAULT
    out_dir    = sys.argv[4] if len(sys.argv) > 4 else OUT_DIR_DEFAULT

    # ── 1. Load MDB data ────────────────────────────────────────────────────
    data = load_patient_session(mdb_path, patient_id)
    if not data:
        sys.exit(1)

    pat  = data['patient']
    sess = data['session']

    out = {
        'patient': {
            'pat_handle': pat['pat_handle'],
            'patient_id': pat['patient_id'],
            'name':       pat['name'],
            'title':      pat['title'],
            'dob':        pat['dob'].isoformat() if pat.get('dob') else '',
            'gender':     pat.get('gender', 'Female'),
            'ethnicity':  pat.get('ethnicity', ''),
            'height_cm':  pat.get('height_cm') or 0,
            'weight_kg':  pat.get('weight_kg') or 0,
            'bmi':        pat.get('bmi') or 0,
            'physician':  pat.get('physician', ''),
        },
        'session': {
            'scan_date':      sess['scan_date'].strftime('%Y-%m-%d %H:%M:%S') if sess.get('scan_date') else '',
            'scanner_serial': sess.get('scanner_serial') or '',
            'software':       sess.get('software') or '',
            'ntx_filename':   sess.get('ntx_filename'),
            'spine':          sess.get('spine', {}),
            'left_femur':     sess.get('left_femur', {}),
            'right_femur':    sess.get('right_femur', {}),
            'left_forearm':   sess.get('left_forearm', {}),
            'right_forearm':  sess.get('right_forearm', {}),
        },
    }

    Path(out_dir).mkdir(parents=True, exist_ok=True)
    json_path = Path(out_dir) / f'{patient_id}_raw_osteo.json'
    json_path.write_text(json.dumps(out, indent=2, default=_serial))
    print(f'JSON written: {json_path}')
    print(f"  Spine regions:       {list(out['session']['spine'].keys())}")
    print(f"  Left femur regions:  {list(out['session']['left_femur'].keys())}")
    print(f"  Right femur regions: {list(out['session']['right_femur'].keys())}")

    # ── 2. Extract images from XPS files ───────────────────────────────────
    xps_map = detect_xps_files(patient_id, xps_dir)
    if not xps_map:
        logging.warning('No XPS files found in %s for patient %s', xps_dir, patient_id)
        return

    images = extract_osteo_images(
        spine_xps        = xps_map.get('spine', ''),
        left_femur_xps   = xps_map.get('left_femur', ''),
        right_femur_xps  = xps_map.get('right_femur', ''),
        left_forearm_xps  = xps_map.get('left_forearm', ''),
        right_forearm_xps = xps_map.get('right_forearm', ''),
    )

    img_dir = Path(out_dir) / patient_id
    img_dir.mkdir(parents=True, exist_ok=True)

    name_map = {
        'spine':        'img_spine.png',
        'left_femur':   'img_left_femur.png',
        'right_femur':  'img_right_femur.png',
        'left_forearm':  'img_left_forearm.png',
        'right_forearm': 'img_right_forearm.png',
    }
    for label, img in images.items():
        out_path = img_dir / name_map[label]
        img.save(str(out_path))
        print(f'Image saved: {out_path}  ({img.size[0]}x{img.size[1]})')

    missing = [k for k in ('spine', 'left_femur', 'right_femur') if k not in images]
    if missing:
        logging.warning('Missing images: %s', missing)


if __name__ == '__main__':
    main()
