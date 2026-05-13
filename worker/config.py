"""
Central configuration for SDRC DEXA worker.
Edit paths and credentials before deploying on the Windows workstation.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Scanner data paths (Windows production) ───────────────────────────────
MDB_PATH        = os.getenv("MDB_PATH",     r"C:\GE\Lunar\Data\lunar.mdb")
XPS_WATCH_DIR   = os.getenv("XPS_WATCH_DIR", r"C:\GE\Lunar\Data")
OUTPUT_PDF_DIR  = os.getenv("OUTPUT_PDF_DIR", r"C:\SDRC\Reports")

# ── Dev/test overrides (macOS / Linux) ────────────────────────────────────
# Set these in a .env file when running outside Windows:
#   MDB_PATH=/Users/pav/projects/bmd/machine-data/data-2026/lunar.mdb
#   XPS_WATCH_DIR=/Users/pav/projects/bmd/machine-data/data-2026
#   OUTPUT_PDF_DIR=/tmp/sdrc-reports

# ── Supabase ───────────────────────────────────────────────────────────────
SUPABASE_URL    = os.getenv("SUPABASE_URL",     "https://supabase.sdrc.in")
SUPABASE_KEY    = os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY", "your-service-role-key")

# ── Clinic identity (printed on every report) ─────────────────────────────
CLINIC_NAME     = "SDRC Diagnostics"
CLINIC_ADDRESS  = "Jade Arcade, Ground Floor, MG Road, Secunderabad 500003"
CLINIC_PHONE    = ""          # optional, shown in footer
SCANNER_ID      = "NT+152585"
SOFTWARE        = "enCORE v12.30"

# ── Worker behaviour ──────────────────────────────────────────────────────
POLL_INTERVAL   = 30          # seconds between MDB polls
PROCESSED_DB    = os.getenv("PROCESSED_DB", "processed.db")   # SQLite dedup store
GENERATOR_VER   = "1.0.0"

# ── Frontend URL (opened by tray app) ─────────────────────────────────────
FRONTEND_URL    = os.getenv("FRONTEND_URL", "http://localhost:3000")

# ── Derived ───────────────────────────────────────────────────────────────
Path(OUTPUT_PDF_DIR).mkdir(parents=True, exist_ok=True)
