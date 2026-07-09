"""
MDB parser for GE Lunar DPX enCORE database (lunar.mdb).

TRUE label mappings verified against actual data from SDRC scanner:

  Scan session structure (grouped by scan_handle):
    scantype=0,  site=0, side=0  → Total body scan  (spine labels 19-22 + composites)
    scantype=1,  site=1, side=2  → Right hip/femur  (labels 0-4)
    scantype=2,  site=1, side=1  → Left hip/femur   (labels 0-4)
    scantype=10                  → Lateral spine
    scantype=21                  → Report record — skip

  Femur Densitometry labels (both sides):
    0=Neck, 1=Wards, 2=Trochanter, 3=InterTroch, 4=Total

  Spine Densitometry labels (in total-body img, scantype=0):
    19=L1, 20=L2, 21=L3, 22=L4
    26=L1-L2, 27=L1-L3, 28=L1-L4, 29=L2-L3, 30=L2-L4, 31=L3-L4

  XPS is authoritative for BMD / T-score / Z-score.
  MDB is used for BMC, Area, and patient demographics.
"""

import subprocess
import csv
import io
import sys
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# ── Label mappings ────────────────────────────────────────────────────────
FEMUR_LABELS = {
    0: 'Neck',
    1: 'Wards',
    2: 'Trochanter',
    3: 'InterTroch',
    4: 'Total',
}

SPINE_LABELS_TOTALBODY = {
    19: 'L1',
    20: 'L2',
    21: 'L3',
    22: 'L4',
    26: 'L1-L2',
    27: 'L1-L3',
    28: 'L1-L4',
    29: 'L2-L3',
    30: 'L2-L4',
    31: 'L3-L4',
}

FOREARM_LABELS = {
    1: 'Radius UD',
    2: 'Ulna UD',
    3: 'Radius 33%',
    4: 'Ulna 33%',
    25: 'Both UD',
    26: 'Both 33%',
    27: 'Radius Total',
    28: 'Ulna Total',
    29: 'Both Total',
}

DISPLAY_SPINE = ['L1', 'L2', 'L3', 'L4', 'L1-L4']
DISPLAY_FEMUR = ['Neck', 'Wards', 'Trochanter', 'Total']
DISPLAY_FOREARM = ['Radius UD', 'Ulna UD', 'Radius 33%', 'Ulna 33%', 'Both UD', 'Both 33%', 'Radius Total', 'Ulna Total', 'Both Total']

# Composition labels — two label sets depending on scan type:
#
# Total-body scan (labels verified against SDRC scanner + XPS cross-check):
#   1=Arms  2=Legs  3=Trunk  7=Total  59=Android  60=Gynoid
#   Values stored in grams (fat_mass=15000 → 15 kg fat)
#
# Osteo (AP Spine + Dual Femur) estimated composition:
#   0=Total  1=AP Spine region  5=Android  6=Gynoid
#   Values stored as percentage×10 (fat_mass=398.5 → 39.85% fat)
#   Confirmed against GE Lunar DPX display for patient 20260513066
TOTALBODY_COMP_LABELS = {
    # True total-body scan
    1:  'Arms',
    2:  'Legs',
    3:  'Trunk',
    7:  'Total',
    59: 'Android',
    60: 'Gynoid',
    # Osteo estimated composition (AP Spine + Femur analysis)
    0:  'Total',     # Estimated Total Body
    5:  'Android',   # Estimated Android region
    6:  'Gynoid',    # Estimated Gynoid region
    # label=1 for osteo = AP Spine estimate; overlaps with Arms above but
    # 'Arms' is ignored in reporting — only Total/Android/Gynoid are used
}


# Total-body bone density region labels (Densitometry table, scantype=10)
# Verified against XPS output and Densitometry rows for SDRC scanner.
TOTALBODY_BONE_LABELS = {
    0: 'Head',
    1: 'Arms',
    2: 'Legs',
    3: 'Trunk',
    4: 'Ribs',
    5: 'Pelvis',
    6: 'Spine',
    7: 'Total',
}


# ── Excel serial date helper ───────────────────────────────────────────────
EXCEL_EPOCH = datetime(1899, 12, 30)

def excel_to_datetime(serial) -> Optional[datetime]:
    if serial is None or serial == '' or float(serial) == 0:
        return None
    return EXCEL_EPOCH + timedelta(days=float(serial))


# ── MDB backend abstraction ───────────────────────────────────────────────
def _read_table_mdbtools(mdb_path: str, table: str) -> list[dict]:
    """Read an MDB table via mdb-export (macOS / Linux dev)."""
    result = subprocess.run(
        ['mdb-export', mdb_path, table],
        capture_output=True, text=True, check=True,
    )
    reader = csv.DictReader(io.StringIO(result.stdout))
    return list(reader)


def _read_table_pyodbc(mdb_path: str, table: str) -> list[dict]:
    """Read an MDB table via pyodbc + Access ODBC driver (Windows production)."""
    import pyodbc
    conn_str = (
        r"Driver={Microsoft Access Driver (*.mdb, *.accdb)};"
        f"Dbq={mdb_path};"
    )
    con = pyodbc.connect(conn_str)
    cur = con.cursor()
    cur.execute(f"SELECT * FROM [{table}]")
    cols = [c[0] for c in cur.description]
    rows = [dict(zip(cols, row)) for row in cur.fetchall()]
    con.close()
    return rows


def _read_table(mdb_path: str, table: str) -> list[dict]:
    if sys.platform == 'win32':
        try:
            return _read_table_pyodbc(mdb_path, table)
        except Exception as e:
            log.warning("pyodbc failed (%s), falling back to mdb-export", e)
    return _read_table_mdbtools(mdb_path, table)


def _safe_float(val) -> Optional[float]:
    try:
        v = float(val)
        return None if v == 0.0 else v
    except (TypeError, ValueError):
        return None


def _safe_float_score(val) -> Optional[float]:
    """Like _safe_float but treats 0.0 as a valid score (returns 0.0, not None)."""
    try:
        v = float(val)
        # Only reject if the raw value is empty/None/unparseable
        return v
    except (TypeError, ValueError):
        return None


def _label_int(val) -> int:
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return -1


# ── Main parser ───────────────────────────────────────────────────────────
class MdbParser:
    """Loads all tables from lunar.mdb and provides patient/scan lookups."""

    def __init__(self, mdb_path: str):
        self.mdb_path = str(mdb_path)
        log.info("Loading MDB: %s", mdb_path)
        self._patients     = self._index_by('Patient',     'pat_handle')
        self._exams        = self._load_exams()
        self._densitometry = self._load_densitometry()
        self._composition  = self._load_composition()
        self._norm         = self._load_norm()
        log.info("MDB loaded: %d patients, %d scans",
                 len(self._patients), len(self._exams))

    # ── loaders ──────────────────────────────────────────────────────────
    def _index_by(self, table: str, key: str) -> dict:
        rows = _read_table(self.mdb_path, table)
        return {r[key]: r for r in rows if r.get(key)}

    def _load_exams(self) -> list[dict]:
        rows = _read_table(self.mdb_path, 'Exam')
        out = []
        for r in rows:
            handle = r.get('img_handle', '')
            if handle.startswith('rpt_'):
                continue
            try:
                scantype = int(float(r['scantype']))
            except (TypeError, ValueError, KeyError):
                continue
            if scantype == 21:
                continue
            r['_scantype_int'] = scantype
            r['_side_int'] = int(float(r.get('side', 0)))
            r['_acq_dt'] = excel_to_datetime(r.get('acq_time'))
            out.append(r)
        return out

    def _load_composition(self) -> dict[str, list[dict]]:
        """Returns dict keyed by img_handle → list of Composition rows."""
        rows = _read_table(self.mdb_path, 'Composition')
        index: dict[str, list[dict]] = {}
        for r in rows:
            h = r.get('img_handle', '')
            if h:
                index.setdefault(h, []).append(r)
        return index

    def _load_densitometry(self) -> dict[str, list[dict]]:
        """Returns dict keyed by img_handle → list of densitometry rows."""
        rows = _read_table(self.mdb_path, 'Densitometry')
        index: dict[str, list[dict]] = {}
        for r in rows:
            h = r.get('img_handle', '')
            if h:
                index.setdefault(h, []).append(r)
        return index

    def _load_norm(self) -> dict[str, dict]:
        """Returns dict keyed by result_handle (= dens_handle) → norm row (type=0 preferred)."""
        rows = _read_table(self.mdb_path, 'Norm')
        index: dict[str, dict] = {}
        for r in rows:
            rh = r.get('result_handle', '')
            if not rh:
                continue
            norm_type = int(float(r.get('type', -1)))
            if norm_type != 0:
                continue
            # Keep only if percent_ya or T-score or Z-score is non-null
            pct_ya = _safe_float(r.get('percent_ya'))
            t = _safe_float(r.get('zsco_bmd_ya'))
            z = _safe_float_score(r.get('zsco_bmd_am'))
            if pct_ya is None and t is None and z is None:
                continue
            index[rh] = r
        return index

    # ── public API ────────────────────────────────────────────────────────
    def list_patients(self) -> list[dict]:
        """Return all patients as dicts with parsed demographics."""
        return [self._parse_patient(p) for p in self._patients.values()]

    def find_patient(self, patient_id: str) -> Optional[dict]:
        for p in self._patients.values():
            if p.get('patient_id', '').strip() == patient_id.strip():
                return self._parse_patient(p)
        return None

    def get_scan_sessions(self, pat_handle: str) -> list[dict]:
        """
        Return all scan sessions for a patient, newest first.
        Each session groups scantype 0+1+2 under one scan_handle.
        """
        relevant = [e for e in self._exams if e.get('pat_handle') == pat_handle]
        if not relevant:
            return []

        # Group by scan_handle
        sessions: dict[str, list] = {}
        for e in relevant:
            sh = e.get('scan_handle', '')
            sessions.setdefault(sh, []).append(e)

        result = []
        for sh, imgs in sessions.items():
            session = self._parse_session(sh, imgs)
            if session:
                result.append(session)

        result.sort(key=lambda s: s['scan_date'] or datetime.min, reverse=True)
        return result

    def get_latest_session(self, pat_handle: str) -> Optional[dict]:
        sessions = self.get_scan_sessions(pat_handle)
        return sessions[0] if sessions else None

    def get_all_scan_handles(self) -> list[str]:
        """All scan_handles in the DB (for watcher)."""
        seen = set()
        out = []
        for e in self._exams:
            sh = e.get('scan_handle', '')
            if sh and sh not in seen:
                seen.add(sh)
                out.append(sh)
        return out

    # ── internal parsing ─────────────────────────────────────────────────
    def _parse_patient(self, row: dict) -> dict:
        dob = excel_to_datetime(row.get('birth_time'))
        height = _safe_float(row.get('height'))
        weight = _safe_float(row.get('weight'))
        bmi = round(weight / (height / 100) ** 2, 1) if height and weight else None
        return {
            'pat_handle': row.get('pat_handle', ''),
            'patient_id': row.get('patient_id', ''),
            'name':       row.get('first_name', '').strip(),
            'title':      row.get('last_name', '').strip(),
            'dob':        dob.date() if dob else None,
            'gender':     row.get('gender', ''),
            'ethnicity':  row.get('ethnicity', ''),
            'height_cm':  height,
            'weight_kg':  weight,
            'bmi':        bmi,
            'physician':  row.get('physician', '').strip(),
        }

    def _parse_session(self, scan_handle: str, imgs: list[dict]) -> Optional[dict]:
        # Identify the three scan images
        # scantype 0 = standard total-body; scantype 10 = total-body on some DPX-NT firmware versions
        body_img  = next((e for e in imgs if e['_scantype_int'] in (0, 10) and e['img_handle'].startswith('img_')), None)
        right_img = next((e for e in imgs if e['_scantype_int'] == 1 and e['_side_int'] == 2), None)
        left_img  = next((e for e in imgs if e['_scantype_int'] == 2 and e['_side_int'] == 1), None)

        if not any([body_img, right_img, left_img]):
            return None

        # Use body scan date as session date; fall back to any available
        primary = body_img or right_img or left_img
        scan_date = primary['_acq_dt']

        scanner_serial = primary.get('scanner_id', '').strip() or None
        software = primary.get('acquisition_version', '').strip() or None
        filename = primary.get('filename', '').strip() or None

        # Determine scan type from MDB scantypes present in this session:
        #   scantype 10 → total body scan (full-body DXA)
        #   scantype 0 with left+right femur → osteo (AP Spine + Dual Femur)
        #   scantype 0 alone → spine-only osteo
        has_tb_scantype = any(e['_scantype_int'] == 10 for e in imgs)
        mdb_scan_type = 'total_body' if has_tb_scantype else 'osteo'

        session = {
            'scan_handle':    scan_handle,
            'scan_date':      scan_date,
            'scanner_serial': scanner_serial,
            'software':       software,
            'ntx_filename':   filename,
            'mdb_scan_type':  mdb_scan_type,   # 'osteo' | 'total_body'
            'spine':          {},
            'left_femur':     {},
            'right_femur':    {},
            'left_forearm':   {},
            'right_forearm':  {},
        }

        # Spine from body/spine scan
        if body_img:
            session['spine'] = self._extract_spine(body_img['img_handle'])
            # GE Lunar estimates body composition (Android/Gynoid/Total) from
            # the AP Spine + Femur analysis and stores it in the Composition
            # table linked to the spine img_handle — extract it here.
            comp = self.get_totalbody_regions(body_img['img_handle'])
            if comp:
                session['estimated_composition'] = comp

        # Left femur
        if left_img:
            session['left_femur'] = self._extract_femur(left_img['img_handle'])

        # Right femur
        if right_img:
            session['right_femur'] = self._extract_femur(right_img['img_handle'])

        # Left forearm (scantype=12, side=1)
        left_forearm_img = next((e for e in imgs if e['_scantype_int'] == 12 and e['_side_int'] == 1), None)
        if left_forearm_img:
            session['left_forearm'] = self._extract_forearm(left_forearm_img['img_handle'])

        # Right forearm (scantype=12, side=2)
        right_forearm_img = next((e for e in imgs if e['_scantype_int'] == 12 and e['_side_int'] == 2), None)
        if right_forearm_img:
            session['right_forearm'] = self._extract_forearm(right_forearm_img['img_handle'])

        return session

    def get_totalbody_regions(self, img_handle: str) -> dict:
        """
        Return per-region body composition from Composition table.
        Keys: Arms, Trunk, Legs, Android, Gynoid, Total
        Each value: {fat_g, lean_g, bone_g, total_g, fat_pct}
        """
        rows = self._composition.get(img_handle, [])
        result = {}
        for row in rows:
            label = _label_int(row.get('label'))
            region = TOTALBODY_COMP_LABELS.get(label)
            if region is None:
                continue
            fat_g  = abs(float(row.get('fat_mass',  0) or 0))
            lean_g = abs(float(row.get('lean_mass', 0) or 0))
            bone_g = abs(float(row.get('bone_mass', 0) or 0))
            total_g = fat_g + lean_g + bone_g
            fat_pct = round(fat_g / total_g * 100, 1) if total_g > 0 else None
            result[region] = {
                'fat_g':   round(fat_g),
                'lean_g':  round(lean_g),
                'bone_g':  round(bone_g),
                'total_g': round(total_g),
                'fat_pct': fat_pct,
            }
        return result

    def get_totalbody_bone_regions(self, img_handle: str) -> dict:
        """
        Return per-region bone density from Densitometry table for a total-body scan.
        Keys: Head, Arms, Legs, Trunk, Ribs, Pelvis, Spine, Total
        Each value: {bmd, bmc, area} — Total also has {T, Z, pYA} from Norm table.
        """
        dens_rows = self._densitometry.get(img_handle, [])
        result = {}
        for row in dens_rows:
            label = _label_int(row.get('label'))
            region = TOTALBODY_BONE_LABELS.get(label)
            if region is None:
                continue
            norm = self._norm.get(row.get('dens_handle', ''), {})
            entry = {
                'bmd':  _safe_float(row.get('bmd')),
                'bmc':  _safe_float(row.get('bmc')),
                'area': _safe_float(row.get('area')),
            }
            t = _safe_float_score(norm.get('zsco_bmd_ya'))
            z = _safe_float_score(norm.get('zsco_bmd_am'))
            pya = _safe_float(norm.get('percent_ya'))
            if t is not None:  entry['T']   = t
            if z is not None:  entry['Z']   = z
            if pya is not None: entry['pYA'] = pya
            result[region] = entry
        return result

    def _get_patient_id(self, pat_handle: str) -> str:
        """Return the patient_id string for a given pat_handle (or '' if not found)."""
        row = self._patients.get(pat_handle)
        if row:
            return row.get('patient_id', '').strip()
        return ''

    def find_totalbody_img_handle(self, pat_handle: str) -> str:
        """
        Return img_handle for the most recent total-body scan (scantype=10).

        The scanner may create TWO patient records sharing the same patient_id
        but with different pat_handle values.  This method looks up all
        pat_handles that share the same patient_id as the supplied pat_handle,
        then searches scantype=10 exams across ALL of those pat_handles.
        """
        patient_id = self._get_patient_id(pat_handle)
        if patient_id:
            # Collect all pat_handles that share this patient_id
            related_handles = {
                ph for ph, row in self._patients.items()
                if row.get('patient_id', '').strip() == patient_id
            }
        else:
            related_handles = {pat_handle}

        cands = [
            e for e in self._exams
            if e.get('pat_handle') in related_handles and e.get('_scantype_int') == 10
        ]
        if not cands:
            return ''
        cands.sort(key=lambda e: e.get('_acq_dt') or datetime.min, reverse=True)
        return cands[0].get('img_handle', '')

    def _extract_spine(self, img_handle: str) -> dict:
        dens_rows = self._densitometry.get(img_handle, [])
        result = {}
        for row in dens_rows:
            label = _label_int(row.get('label'))
            site = SPINE_LABELS_TOTALBODY.get(label)
            if site is None or site not in DISPLAY_SPINE:
                continue
            norm = self._norm.get(row.get('dens_handle', ''), {})
            result[site] = {
                'bmd':   _safe_float(row.get('bmd')),
                'bmc':   _safe_float(row.get('bmc')),
                'area':  _safe_float(row.get('area')),
                'T':     _safe_float_score(norm.get('zsco_bmd_ya')),
                'Z':     _safe_float_score(norm.get('zsco_bmd_am')),
                'pYA':   _safe_float(norm.get('percent_ya')),
                'source': 'MDB',
            }
        return result

    def _extract_femur(self, img_handle: str) -> dict:
        dens_rows = self._densitometry.get(img_handle, [])
        result = {}
        for row in dens_rows:
            label = _label_int(row.get('label'))
            site = FEMUR_LABELS.get(label)
            if site is None or site not in DISPLAY_FEMUR:
                continue
            norm = self._norm.get(row.get('dens_handle', ''), {})
            result[site] = {
                'bmd':   _safe_float(row.get('bmd')),
                'bmc':   _safe_float(row.get('bmc')),
                'area':  _safe_float(row.get('area')),
                'T':     _safe_float_score(norm.get('zsco_bmd_ya')),
                'Z':     _safe_float_score(norm.get('zsco_bmd_am')),
                'pYA':   _safe_float(norm.get('percent_ya')),
                'source': 'MDB',
            }
        return result

    def _extract_forearm(self, img_handle: str) -> dict:
        dens_rows = self._densitometry.get(img_handle, [])
        result = {}
        for row in dens_rows:
            label = _label_int(row.get('label'))
            site = FOREARM_LABELS.get(label)
            if site is None or site not in DISPLAY_FOREARM:
                continue
            norm = self._norm.get(row.get('dens_handle', ''), {})
            result[site] = {
                'bmd':   _safe_float(row.get('bmd')),
                'bmc':   _safe_float(row.get('bmc')),
                'area':  _safe_float(row.get('area')),
                'T':     _safe_float_score(norm.get('zsco_bmd_ya')),
                'Z':     _safe_float_score(norm.get('zsco_bmd_am')),
                'pYA':   _safe_float(norm.get('percent_ya')),
                'source': 'MDB',
            }
        return result


# ── Convenience function ──────────────────────────────────────────────────
def load_patient_session(mdb_path: str, patient_id: str,
                         scan_index: int = 0) -> Optional[dict]:
    """
    High-level helper: loads MDB, finds patient, returns a scan session.

    scan_index: 0 = latest (default), 1 = second most recent, etc.
    """
    parser = MdbParser(mdb_path)
    patient = parser.find_patient(patient_id)
    if not patient:
        log.error("Patient %s not found in MDB", patient_id)
        return None
    sessions = parser.get_scan_sessions(patient['pat_handle'])
    if not sessions:
        log.error("No scan sessions for patient %s", patient_id)
        return None
    if scan_index >= len(sessions):
        log.error("scan_index %d out of range — patient has %d session(s)", scan_index, len(sessions))
        return None
    return {'patient': patient, 'session': sessions[scan_index]}


def list_patient_sessions(mdb_path: str, patient_id: str) -> list[dict]:
    """
    Return all scan sessions for a patient, newest first.
    Each entry: {'scan_index': int, 'scan_date': datetime, 'scan_handle': str}
    """
    parser = MdbParser(mdb_path)
    patient = parser.find_patient(patient_id)
    if not patient:
        return []
    sessions = parser.get_scan_sessions(patient['pat_handle'])
    return [
        {
            'scan_index':  i,
            'scan_date':   s.get('scan_date'),
            'scan_handle': s.get('scan_handle', ''),
        }
        for i, s in enumerate(sessions)
    ]
