# SDRC DEXA BMD Report System

Automated clinical bone-density (BMD/DEXA) PDF reports from a GE Lunar DPX scanner.

**Stack:** Python worker (Windows) · Supabase (self-hosted) · Next.js 14 frontend

---

## Quick start

### 1. Supabase

Run the migration against your self-hosted instance:

```sql
-- In Supabase SQL editor:
\i supabase/migrations/001_initial.sql
```

Create the storage bucket in the Supabase dashboard → Storage → `pdfs` (set to Public).

---

### 2. Worker (Windows workstation)

```bat
cd worker
python -m pip install -r requirements.txt
copy .env.example .env
REM Edit .env with your paths and Supabase credentials

REM Run once to test:
python test_parser.py

REM Run in background via tray:
pythonw tray_app.py
```

**Task Scheduler startup:** Action → `pythonw.exe C:\path\to\worker\tray_app.py`

---

### 3. Frontend

```bash
cd frontend
cp .env.local.example .env.local
# Edit .env.local with your Supabase URL and keys

npm install
npm run dev        # development
npm run build && npm start   # production on port 3000
```

Access from any device on the LAN: `http://<server-ip>:3000`

---

## Architecture

```
GE Lunar DPX scanner  →  lunar.mdb  +  *.xps  (on Windows workstation)
                                            │
                            Python worker  (polls every 30s)
                            ├── parse_mdb.py   (MDB → structured dict)
                            ├── parse_xps.py   (XPS → images + BMD values)
                            ├── render_pdf.py  (5-page ReportLab PDF)
                            └── sync_supabase.py (upload + DB upsert)
                                            │
                                    Supabase (self-hosted LAN)
                                    ├── Postgres: patients, scans, bmd_results, reports
                                    └── Storage: pdfs/{pid}/{date}.pdf
                                            │
                                  Next.js 14 frontend (port 3000)
                                  ├── /               patient list + search
                                  ├── /patients/[id]  patient detail + trend chart
                                  └── /scans/[id]     scan detail + inline PDF
```

---

## Key discoveries (corrected from original spec)

The original build prompt had incorrect label mappings. Verified against actual SDRC data:

| Scan type in DB | What it actually is |
|---|---|
| `scantype=0, site=0, side=0` | Total body scan — **also contains spine data** at labels 19–22 |
| `scantype=1, site=1, side=2` | **Right femur** (NOT AP Spine as spec stated) |
| `scantype=2, site=1, side=1` | **Left femur** (NOT Dual Femur as spec stated) |
| `scantype=21` | Report record — skip |

**Spine Densitometry labels** (in total-body img, `scantype=0`):

| Label | Site |
|---|---|
| 19 | L1 |
| 20 | L2 |
| 21 | L3 |
| 22 | L4 |
| 28 | L1-L4 |

**Femur Densitometry labels** (both sides, labels 0–4):

| Label | Site |
|---|---|
| 0 | Neck |
| 1 | Wards |
| 2 | Trochanter |
| 3 | InterTroch |
| 4 | Total |

**Data authority:**
- BMD, T-score, Z-score → **XPS is authoritative** (printed values)
- BMC, Area, Ward's, Trochanter → **MDB** (not printed in XPS)

---

## Test validation

All 35 assertions pass against real SDRC patient data (DEEPA BAHIRWANI, PID 20260323063):

```
python worker/test_parser.py
```

Expected values verified: spine L1–L4 BMD/T/Z, both femurs BMD/T/Z/BMC/Area,
worst T=-1.6 (Osteopenia), 820 KB PDF generated.

---

## Phase 2 (future)

Total-body composition report (lean mass, fat mass, body silhouette image) when
SDRC upgrades to GE iDXA or Lunar Prodigy. MDB `Composition` table already parsed.
Binary `.ntx/.nts/.ntb` files require GE enCORE SDK — raise with GE Healthcare India.
