# SDRC Bone Density Collector — Windows Setup Guide

This installs the **osteo collector** on the GE Lunar DXA Windows workstation.
No PDF generation, no analysis — just: read MDB + XPS → upload to Supabase.
The Ubuntu server generates reports on demand from the uploaded data.

---

## What you need before starting

- USB drive or network share with the `sdrc-dexa/worker/` folder copied onto it
- Internet access from the Windows machine (to reach Supabase)
- Your Supabase URL and service-role key
- 15–20 minutes

---

## Step 1 — Install Python 3.8

Windows 7 supports Python up to **3.8.10** (later versions drop Win7 support).

1. Download: https://www.python.org/ftp/python/3.8.10/python-3.8.10-amd64.exe  
   (Use the 32-bit `python-3.8.10.exe` if the machine is 32-bit)
2. Run the installer
3. **Important:** tick **"Add Python 3.8 to PATH"** at the bottom of the first screen
4. Click **Install Now**
5. Verify in Command Prompt:
   ```
   python --version
   ```
   Should show `Python 3.8.10`

---

## Step 2 — Install Microsoft Access Database Engine

The MDB reader needs an ODBC driver that matches your Python bitness.

1. Download the **2010 Redistributable**:
   - 64-bit Python: https://www.microsoft.com/en-us/download/details.aspx?id=13255
     → choose `AccessDatabaseEngine_X64.exe`
   - 32-bit Python: same page → `AccessDatabaseEngine.exe`

2. Run the installer, click through defaults.

3. If you get an error about "32-bit Office already installed", run with `/quiet`:
   ```
   AccessDatabaseEngine_X64.exe /quiet
   ```

---

## Step 3 — Copy the worker files

Create this folder on the Windows machine:
```
C:\SDRC\collector\
```

Copy these files from the USB drive / network share:
```
worker/
  collect_osteo.py        ← osteo-specific collection logic (NEW)
  collector_osteo_ui.py   ← the UI window (NEW)
  config.py
  parse_mdb.py
  parse_xps.py
  sync_supabase.py
  requirements_windows.txt
```

Do **not** copy `pipeline.py`, `render_pdf.py`, `watcher.py`, or `tray_app.py` —
they are not needed on this machine.

---

## Step 4 — Install Python packages

Open **Command Prompt as Administrator** (right-click cmd → Run as administrator):

```cmd
cd C:\SDRC\collector
pip install -r requirements_windows.txt
```

`requirements_windows.txt` contents (create this file if not present):
```
httpx==0.27.2
Pillow==9.5.0
numpy==1.24.4
python-dotenv==1.0.1
pyodbc==5.1.0
supabase==2.4.0
```

The install takes 2–3 minutes.

---

## Step 5 — Create the .env file

In `C:\SDRC\collector\` create a file called `.env` (no other extension).

In Notepad: File → Save As → "Save as type: All Files" → name it `.env`

Contents:
```
SUPABASE_URL=https://supabase.sdrc.in
SUPABASE_KEY=your-service-role-key-here

MDB_PATH=C:\GE\Lunar\Data\lunar.mdb
XPS_WATCH_DIR=C:\GE\Lunar\XPS
OUTPUT_PDF_DIR=C:\SDRC\Reports
```

**Key settings:**
- `SUPABASE_URL` — your self-hosted Supabase URL
- `SUPABASE_KEY` — the **service_role** key (not the anon key)
- `MDB_PATH` — full path to `lunar.mdb`
- `XPS_WATCH_DIR` — **designated folder where GE saves XPS files** (see Step 6)

---

## Step 6 — Set up the XPS folder

The collector looks for XPS files named `{MRN}-1.xps`, `{MRN}-2.xps`, `{MRN}-3.xps`
in `XPS_WATCH_DIR`.

**Tell staff** to always save XPS files from GE Lunar like this:

1. After scanning: **File → Save As → XPS Document**
2. Navigate to `XPS_WATCH_DIR` (e.g. `C:\GE\Lunar\XPS`)
3. Name the file exactly: `{MRN}-1.xps` for spine, `{MRN}-2.xps` for left femur, `{MRN}-3.xps` for right femur

The collector will auto-detect which scan is which by reading the XPS text content —
so the numbering can be in any order, but all three files must be saved.

---

## Step 7 — MRN in GE Lunar

**From now on, staff must enter the patient's MRN (Medical Record Number) in the  
GE Lunar "Patient ID" field** — not the accession number.

This is the key that links scans across visits for trend tracking.

Existing patients entered with accession numbers will continue to work for one-off
reports but will not appear in trend analysis.

---

## Step 8 — Test run

Find the MDB path:
```cmd
dir C:\ /s /b 2>nul | findstr /i "lunar.mdb"
```

Test the collector backend:
```cmd
cd C:\SDRC\collector
python collect_osteo.py
```

It will print the most recently scanned patient and their XPS status.

---

## Step 9 — Run the collector UI

```cmd
cd C:\SDRC\collector
python collector_osteo_ui.py
```

The **SDRC Bone Density Collector** window appears:

1. It auto-loads the most recently scanned patient from MDB
2. The XPS panel shows three rows:  
   - ✓ green = XPS file found  
   - ✗ red = XPS file not found
3. If any XPS is missing, a yellow instruction box shows the exact steps to save it from GE Lunar
4. Once all three are ✓ green, click **▲ Collect Scan Data**
5. Progress is shown in the log area below
6. When done, a confirmation dialog appears

The Ubuntu server will generate the PDF report on demand.

---

## Step 10 — Desktop shortcut

1. Right-click desktop → New → Shortcut
2. Location:
   ```
   C:\Python38\pythonw.exe C:\SDRC\collector\collector_osteo_ui.py
   ```
   (`pythonw.exe` opens without a console window)
3. Name it **SDRC Bone Density Collector**

---

## Step 11 — Auto-start with Windows (optional)

1. Press `Win + R` → type `shell:startup` → Enter
2. Copy the desktop shortcut into the Startup folder

---

## What gets uploaded to Supabase

Each upload creates:

**Storage** (`raw-osteo` bucket):
```
raw-osteo/{MRN}/{timestamp}/
  raw_osteo.json          — full MDB data for this patient + session
  img_spine.png           — extracted spine DXA image
  img_left_femur.png      — extracted left femur DXA image
  img_right_femur.png     — extracted right femur DXA image
  {MRN}-1.xps             — raw spine XPS (kept for reprocessing)
  {MRN}-2.xps             — raw left femur XPS
  {MRN}-3.xps             — raw right femur XPS
```

**Database rows** (`bmd_patients`, `bmd_scans`, `bmd_results`):
- Patient demographics (MRN, name, DOB, etc.)
- Scan metadata (date, scanner, software)
- All BMD values for spine + left + right femur regions

---

## Troubleshooting

**"No module named pyodbc"**  
→ Re-run `pip install pyodbc==5.1.0` from an Administrator command prompt

**ODBC error: "Data source name not found"**  
→ Access Database Engine not installed or bitness mismatch.  
  Control Panel → Admin Tools → ODBC Data Sources (64-bit) → Drivers tab.  
  If "Microsoft Access Driver (*.mdb)" is not listed, reinstall the engine.

**"Patient MRN not found in MDB"**  
→ The MRN entered in GE Lunar doesn't match what you typed.  
  Check the exact value in GE Lunar patient details screen.

**XPS files not auto-detected**  
→ Make sure files are named `{MRN}-1.xps`, `{MRN}-2.xps`, `{MRN}-3.xps` in `XPS_WATCH_DIR`.  
  The collector classifies by text content so file order doesn't matter.

**Only 2 of 3 XPS files found**  
→ The missing scan was not exported. Save the XPS from GE Lunar for that scan type,
  then click ⟳ Refresh in the UI.

**Upload fails / no internet**  
→ Test: open Internet Explorer → navigate to your Supabase URL.  
  If it doesn't load, ask IT to whitelist outbound port 443.

**"ImportError: numpy" / "ImportError: Pillow"**  
→ Image extraction depends on these. Install with:
  ```cmd
  pip install Pillow==9.5.0 numpy==1.24.4 --only-binary :all:
  ```

---

## Files on this machine

| File | Purpose |
|---|---|
| `collector_osteo_ui.py` | The UI window — **run this** |
| `collect_osteo.py` | Collection logic (XPS detection, MDB read, upload) |
| `config.py` | Paths and settings (reads `.env`) |
| `parse_mdb.py` | MDB reader |
| `parse_xps.py` | XPS text + image extraction |
| `sync_supabase.py` | Supabase Storage + DB uploader |
| `.env` | Your credentials — **keep this private** |
