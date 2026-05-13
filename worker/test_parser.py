"""
End-to-end parser validation against known-good values for patient DEEPA BAHIRWANI.

Run from the worker/ directory:
  python test_parser.py

Set env vars (or .env) to point at the actual test files:
  MDB_PATH=/path/to/lunar.mdb
  XPS_WATCH_DIR=/path/to/dexa-xps
"""

import os
import sys
import logging
from pathlib import Path

# Allow running from any directory
sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(level=logging.WARNING, format='%(levelname)s: %(message)s')

# ── Expected values (verified from XPS + MDB) ─────────────────────────────
EXPECTED = {
    'patient_name':  'DEEPA BAHIRWANI',
    'patient_id':    '20260323063',
    'dob':           '1959-08-25',
    'age_approx':    66.5,    # ± 0.5
    'height':        146.0,
    'weight':        63.0,
    'bmi':           29.6,    # ± 0.2
    'spine': {
        'L1':    {'bmd': 1.210, 'T':  0.7, 'Z':  2.3},
        'L2':    {'bmd': 1.154, 'T': -0.4, 'Z':  1.3},
        'L3':    {'bmd': 1.077, 'T': -1.0, 'Z':  0.6},
        'L4':    {'bmd': 1.113, 'T': -0.7, 'Z':  1.0},
        'L1-L4': {'bmd': 1.140, 'T': -0.3, 'Z':  1.3},
    },
    'left_femur': {
        'Neck':       {'bmd': 0.809, 'T': -1.6, 'Z': -0.1, 'bmc': 3.80,  'area': 4.69},
        'Wards':      {'bmd': 0.801, 'T': -0.8, 'Z':  1.3, 'bmc': 1.96,  'area': 2.44},
        'Trochanter': {'bmd': 0.685, 'T': -1.4, 'Z': -0.2, 'bmc': 7.07,  'area': 10.32},
        'Total':      {'bmd': 0.830, 'T': -1.4, 'Z': -0.1, 'bmc': 23.63, 'area': 28.47},
    },
    'right_femur': {
        'Neck':  {'bmd': 0.899, 'T': -1.0, 'Z': 0.6},
        'Total': {'bmd': 0.889, 'T': -0.9, 'Z': 0.4},
    },
    'overall': 'Osteopenia',
    'worst_T': -1.6,
}

TOLERANCE = {
    'bmd':  0.002,
    'T':    0.15,
    'Z':    0.15,
    'bmc':  0.10,
    'area': 0.10,
}

PASS_MARK = '\033[92m✓\033[0m'
FAIL_MARK = '\033[91m✗\033[0m'


def _check(desc: str, got, expected, tol: float) -> bool:
    if got is None:
        print(f"  {FAIL_MARK}  {desc}: got None (expected {expected})")
        return False
    if abs(float(got) - float(expected)) > tol:
        print(f"  {FAIL_MARK}  {desc}: got {got:.4f} expected {expected:.4f} "
              f"(diff {abs(float(got)-float(expected)):.4f} > tol {tol})")
        return False
    print(f"  {PASS_MARK}  {desc}: {got:.4f} ≈ {expected}")
    return True


def test_mdb_parser(mdb_path: str) -> bool:
    from parse_mdb import MdbParser

    print("\n─── MDB Parser ─────────────────────────────────────────────")
    parser = MdbParser(mdb_path)
    data = parser.find_patient(EXPECTED['patient_id'])
    if not data:
        print(f"  {FAIL_MARK}  Patient {EXPECTED['patient_id']} not found in MDB")
        return False

    ok = True

    # Demographics
    name = data.get('name', '')
    print(f"\n  Patient name: {name}")
    if EXPECTED['patient_name'] not in name:
        print(f"  {FAIL_MARK}  Name mismatch: got '{name}'")
        ok = False
    else:
        print(f"  {PASS_MARK}  Name OK")

    dob = data.get('dob')
    if str(dob) != EXPECTED['dob']:
        print(f"  {FAIL_MARK}  DOB: got {dob} expected {EXPECTED['dob']}")
        ok = False
    else:
        print(f"  {PASS_MARK}  DOB: {dob}")

    ok &= _check("height", data.get('height_cm'), EXPECTED['height'], 0.5)
    ok &= _check("weight", data.get('weight_kg'), EXPECTED['weight'], 0.5)
    ok &= _check("bmi",    data.get('bmi'),        EXPECTED['bmi'],    0.3)

    # Scan session
    session = parser.get_latest_session(data['pat_handle'])
    if not session:
        print(f"  {FAIL_MARK}  No scan session found")
        return False

    print(f"\n  Scan date: {session.get('scan_date')}")

    print("\n  ─ Left Femur (MDB) ─")
    for site, exp in EXPECTED['left_femur'].items():
        v = session.get('left_femur', {}).get(site) or {}
        ok &= _check(f"L.Femur {site} BMD",  v.get('bmd'),  exp['bmd'],  TOLERANCE['bmd'])
        if 'bmc'  in exp: ok &= _check(f"L.Femur {site} BMC",  v.get('bmc'),  exp['bmc'],  TOLERANCE['bmc'])
        if 'area' in exp: ok &= _check(f"L.Femur {site} Area", v.get('area'), exp['area'], TOLERANCE['area'])

    print("\n  ─ Right Femur (MDB) ─")
    for site, exp in EXPECTED['right_femur'].items():
        v = session.get('right_femur', {}).get(site) or {}
        ok &= _check(f"R.Femur {site} BMD", v.get('bmd'), exp['bmd'], TOLERANCE['bmd'])

    print("\n  ─ Spine from total-body scan (MDB) ─")
    for site, exp in EXPECTED['spine'].items():
        v = session.get('spine', {}).get(site) or {}
        ok &= _check(f"Spine {site} BMD", v.get('bmd'), exp['bmd'], TOLERANCE['bmd'])

    return ok


def test_xps_parser(xps_path: str) -> bool:
    from parse_xps import parse_xps_bmd, extract_scan_images

    print("\n─── XPS Parser ─────────────────────────────────────────────")
    data = parse_xps_bmd(xps_path)

    ok = True

    print("\n  ─ Spine (XPS) ─")
    for site, exp in EXPECTED['spine'].items():
        v = data.get('spine', {}).get(site) or {}
        ok &= _check(f"Spine {site} BMD", v.get('bmd'), exp['bmd'], TOLERANCE['bmd'])
        ok &= _check(f"Spine {site} T",   v.get('T'),   exp['T'],   TOLERANCE['T'])
        ok &= _check(f"Spine {site} Z",   v.get('Z'),   exp['Z'],   TOLERANCE['Z'])

    print("\n  ─ Left Femur (XPS) ─")
    for site in ['Neck', 'Total']:
        exp = EXPECTED['left_femur'][site]
        v = data.get('left_femur', {}).get(site) or {}
        ok &= _check(f"L.Femur {site} BMD", v.get('bmd'), exp['bmd'], TOLERANCE['bmd'])
        ok &= _check(f"L.Femur {site} T",   v.get('T'),   exp['T'],   TOLERANCE['T'])
        ok &= _check(f"L.Femur {site} Z",   v.get('Z'),   exp['Z'],   TOLERANCE['Z'])

    print("\n  ─ Right Femur (XPS) ─")
    for site, exp in EXPECTED['right_femur'].items():
        v = data.get('right_femur', {}).get(site) or {}
        ok &= _check(f"R.Femur {site} BMD", v.get('bmd'), exp['bmd'], TOLERANCE['bmd'])
        ok &= _check(f"R.Femur {site} T",   v.get('T'),   exp['T'],   TOLERANCE['T'])

    print("\n  ─ Scan images ─")
    images = extract_scan_images(xps_path)
    for label in ['spine', 'left_femur', 'right_femur']:
        if label in images:
            img = images[label]
            print(f"  {PASS_MARK}  {label}: {img.size[0]}×{img.size[1]} px")
        else:
            print(f"  {FAIL_MARK}  {label}: image not found")
            ok = False

    return ok


def test_pdf_render(mdb_path: str, xps_path: str) -> bool:
    from parse_mdb import MdbParser
    from parse_xps import parse_xps_bmd, extract_scan_images, reconcile
    from render_pdf import render_pdf, worst_T, classify
    from pipeline import build_report_data

    print("\n─── PDF Render ─────────────────────────────────────────────")
    parser = MdbParser(mdb_path)
    patient = parser.find_patient(EXPECTED['patient_id'])
    session = parser.get_latest_session(patient['pat_handle'])

    xps_data = parse_xps_bmd(xps_path)
    scan_images = extract_scan_images(xps_path)
    merged = reconcile(xps_data, session)

    report_data = build_report_data(patient, session, merged, scan_images)
    pdf_bytes = render_pdf(report_data)

    ok = len(pdf_bytes) > 50_000   # sanity: PDF should be >50KB
    print(f"  {'✓' if ok else '✗'}  PDF size: {len(pdf_bytes):,} bytes")

    # Verify worst T
    wt, ws = worst_T(report_data)
    ok2 = wt is not None and abs(wt - EXPECTED['worst_T']) < 0.15
    print(f"  {'✓' if ok2 else '✗'}  Worst T-score: {wt} (expected {EXPECTED['worst_T']}) — {ws}")

    _, _, label = classify(wt), None, None
    label, _, _ = classify(wt)
    ok3 = label == EXPECTED['overall']
    print(f"  {'✓' if ok3 else '✗'}  Classification: {label} (expected {EXPECTED['overall']})")

    out = Path(os.getenv('OUTPUT_PDF_DIR', '/tmp/sdrc-reports'))
    out.mkdir(parents=True, exist_ok=True)
    out_path = out / 'test_deepa_bahirwani.pdf'
    out_path.write_bytes(pdf_bytes)
    print(f"  {PASS_MARK}  Saved to: {out_path}")

    return ok and ok2 and ok3


# ── Main ──────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    from dotenv import load_dotenv
    load_dotenv()

    mdb  = os.getenv('MDB_PATH',     '../machine-data/data/lunar.mdb')
    xdir = os.getenv('XPS_WATCH_DIR', '../machine-data/dexa-xps')
    xps  = str(Path(xdir) / '20260323063.xps')

    print(f"MDB:  {mdb}")
    print(f"XPS:  {xps}")

    results = []
    results.append(('MDB Parser',  test_mdb_parser(mdb)))
    results.append(('XPS Parser',  test_xps_parser(xps)))
    results.append(('PDF Render',  test_pdf_render(mdb, xps)))

    print("\n─── Summary ────────────────────────────────────────────────")
    all_ok = True
    for name, passed in results:
        mark = PASS_MARK if passed else FAIL_MARK
        print(f"  {mark}  {name}")
        if not passed:
            all_ok = False

    sys.exit(0 if all_ok else 1)
