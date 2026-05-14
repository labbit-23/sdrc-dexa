"""
Quick diagnostic: dump Composition table rows for recent osteo patients.
Run on Ubuntu: python debug_composition.py
"""
import sys
import config
from parse_mdb import MdbParser, TOTALBODY_COMP_LABELS, _label_int

parser = MdbParser(config.MDB_PATH)

print(f"Total Composition rows in MDB: {sum(len(v) for v in parser._composition.values())}")
print(f"Unique img_handles with composition: {len(parser._composition)}\n")

# Check first 5 composition img_handles — show what labels they have
print("Sample composition rows (first 5 img_handles):")
for ih, rows in list(parser._composition.items())[:5]:
    labels = [(_label_int(r.get('label')), r.get('fat_mass'), r.get('lean_mass')) for r in rows]
    known = [(TOTALBODY_COMP_LABELS.get(l), f, ln) for l, f, ln in labels if TOTALBODY_COMP_LABELS.get(l)]
    print(f"  {ih}: {len(rows)} rows, known regions: {[r for r,_,_ in known]}")

print()

# Find an osteo patient and check their composition
from parse_mdb import load_patient_session
import os

# Use first recent exam to find a patient
recent_exams = sorted(
    [e for e in parser._exams if e.get('_acq_dt')],
    key=lambda e: e['_acq_dt'], reverse=True
)[:10]

seen = set()
for exam in recent_exams:
    ph = exam.get('pat_handle', '')
    pat = parser._patients.get(ph)
    if not pat or ph in seen:
        continue
    seen.add(ph)
    pid = pat.get('patient_id', '').strip()
    if not pid:
        continue
    
    # Find their spine img_handle (scantype=0)
    spine_exams = [e for e in parser._exams if e.get('pat_handle') == ph and e.get('_scantype_int') == 0]
    if not spine_exams:
        continue
    
    ih = spine_exams[0].get('img_handle', '')
    comp_rows = parser._composition.get(ih, [])
    comp_data = parser.get_totalbody_regions(ih)
    
    print(f"Patient {pid}  scan_date={exam.get('_acq_dt','')}")
    print(f"  spine img_handle: {ih}")
    print(f"  composition rows in MDB: {len(comp_rows)}")
    if comp_rows:
        for r in comp_rows:
            lbl = _label_int(r.get('label'))
            region = TOTALBODY_COMP_LABELS.get(lbl, f'unknown({lbl})')
            fat = r.get('fat_mass', '?')
            lean = r.get('lean_mass', '?')
            print(f"    label={lbl} ({region})  fat={fat}  lean={lean}")
    if comp_data:
        total = comp_data.get('Total', {})
        print(f"  → Total: fat={total.get('fat_pct')}%  fat_g={total.get('fat_g')}  lean_g={total.get('lean_g')}")
    else:
        print(f"  → No composition data parsed (labels not matching TOTALBODY_COMP_LABELS)")
    print()
