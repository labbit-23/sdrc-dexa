"""
SDRC Osteo Data Collector — Windows UI.

Minimal tkinter window for collecting spine + hip DXA scan data.
Workflow:
  1. App loads → reads MDB, shows the most-recently-scanned patient.
  2. Staff check the XPS status panel (spine ✓ left femur ✓ right femur ✓).
  3. If any XPS missing → clear instructions shown; Upload is blocked.
  4. Staff click "Collect Scan Data" → uploads JSON + images + XPS to Supabase.

Run on Windows:
  pythonw.exe collector_osteo_ui.py
  python     collector_osteo_ui.py       (shows console log)

Requires: Python 3.8+, tkinter (bundled), Pillow, httpx, supabase-py
"""

import logging
import threading
import tkinter as tk
import tkinter.messagebox as mb
from datetime import datetime
from pathlib import Path
from typing import Optional

import config
from collect_osteo import (
    get_latest_patient, get_patient_by_mrn, xps_status,
    upload_osteo_scan, clear_xps_watch_folder,
    get_sessions_for_mrn,
)
from collect_totalbody import (
    detect_totalbody_xps, tb_xps_status, upload_totalbody_scan,
)

log = logging.getLogger(__name__)

# ── Palette ───────────────────────────────────────────────────────────────────
TEAL    = '#0D7377'
TEAL_LT = '#14A9AF'
DARK    = '#0D1B2A'
PANEL   = '#112233'
WHITE   = '#FFFFFF'
LGRAY   = '#B0BEC5'
MGRAY   = '#607080'
GREEN   = '#2E7D32'
GREEN_L = '#4CAF50'
AMBER   = '#E65100'
RED     = '#B71C1C'
RED_L   = '#EF5350'

FONT_TITLE  = ('Helvetica', 20, 'bold')
FONT_BODY   = ('Helvetica', 15)
FONT_SMALL  = ('Helvetica', 12)
FONT_LABEL  = ('Helvetica', 13, 'bold')
FONT_MONO   = ('Courier New', 12)


class OsteoCollectorApp(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title('SDRC — Osteo Data Collector')
        self.geometry('960x840')
        self.resizable(False, False)
        self.configure(bg=DARK)
        self.protocol('WM_DELETE_WINDOW', self._on_close)

        # State
        self._patient: Optional[dict]   = None   # from get_latest_patient()
        self._xps_map: dict[str, str]   = {}     # {'spine': path, ...} or {'bone': path, ...}
        self._scan_date: Optional[datetime] = None
        self._uploading = False
        self._scan_mode: str = 'osteo'            # 'osteo' | 'total_body'

        self._build_ui()
        # Auto-load on startup in a background thread so the window appears fast
        threading.Thread(target=self._load_patient, daemon=True).start()

    # ─── UI construction ─────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Header ──────────────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=TEAL, height=78)
        hdr.pack(fill='x')
        hdr.pack_propagate(False)

        tk.Label(
            hdr, text='SDRC  BONE DENSITY  COLLECTOR',
            bg=TEAL, fg=WHITE, font=FONT_TITLE,
        ).pack(side='left', padx=18, pady=14)

        tk.Label(
            hdr, text=config.CLINIC_NAME,
            bg=TEAL, fg='#B2DFDB', font=FONT_SMALL,
        ).pack(side='right', padx=18)

        # ── Patient card ─────────────────────────────────────────────────────
        pat_frame = tk.Frame(self, bg=PANEL, padx=16, pady=12)
        pat_frame.pack(fill='x', padx=0, pady=(0, 0))

        tk.Label(pat_frame, text='PATIENT',
                 bg=PANEL, fg=MGRAY, font=FONT_SMALL).grid(row=0, column=0, sticky='w')

        self._name_var = tk.StringVar(value='Loading…')
        tk.Label(pat_frame, textvariable=self._name_var,
                 bg=PANEL, fg=WHITE, font=('Helvetica', 21, 'bold')).grid(
            row=1, column=0, sticky='w', pady=(2, 0))

        self._meta_var = tk.StringVar(value='')
        tk.Label(pat_frame, textvariable=self._meta_var,
                 bg=PANEL, fg=LGRAY, font=FONT_SMALL).grid(
            row=2, column=0, sticky='w')

        # MRN entry + Load button (row 3)
        mrn_row = tk.Frame(pat_frame, bg=PANEL)
        mrn_row.grid(row=3, column=0, columnspan=2, sticky='w', pady=(6, 0))
        tk.Label(mrn_row, text='MRN:', bg=PANEL, fg=MGRAY, font=FONT_SMALL).pack(side='left')
        self._mrn_entry = tk.Entry(mrn_row, width=18, bg='#0d1b2a', fg=WHITE,
                                   insertbackground=WHITE, font=FONT_MONO,
                                   relief='flat', bd=4)
        self._mrn_entry.pack(side='left', padx=(4, 6))
        self._mrn_entry.bind('<Return>', lambda e: self._load_by_mrn())
        tk.Button(
            mrn_row, text='Load',
            bg=TEAL, fg=WHITE, activebackground=TEAL_LT,
            font=FONT_SMALL, relief='flat', bd=0, cursor='hand2', padx=8,
            command=self._load_by_mrn,
        ).pack(side='left')
        tk.Label(mrn_row, text=' or ', bg=PANEL, fg=MGRAY, font=FONT_SMALL).pack(side='left')
        tk.Button(
            mrn_row, text='⟳  Latest',
            bg=PANEL, fg=TEAL_LT, activebackground=PANEL, activeforeground=WHITE,
            font=FONT_SMALL, relief='flat', bd=0, cursor='hand2',
            command=lambda: threading.Thread(target=self._load_patient, daemon=True).start(),
        ).pack(side='left')

        pat_frame.columnconfigure(0, weight=1)

        # Separator
        tk.Frame(self, bg='#1a3a55', height=1).pack(fill='x')

        # ── XPS status panel ─────────────────────────────────────────────────
        xps_outer = tk.Frame(self, bg=DARK, pady=12)
        xps_outer.pack(fill='x', padx=18)

        tk.Label(xps_outer, text='XPS FILES', bg=DARK, fg=MGRAY, font=FONT_SMALL).pack(anchor='w')

        self._xps_frame = tk.Frame(xps_outer, bg=DARK)
        self._xps_frame.pack(fill='x', pady=(4, 0))

        # XPS rows — rebuilt dynamically when scan mode changes
        self._xps_rows: dict[str, dict] = {}
        self._mode_badge_var = tk.StringVar(value='')
        tk.Label(xps_outer, textvariable=self._mode_badge_var,
                 bg=DARK, fg=TEAL_LT, font=FONT_SMALL).pack(anchor='w')
        self._build_xps_rows('osteo')

        # ── Session picker (hidden unless patient has >1 scan) ───────────────
        self._session_row = tk.Frame(self, bg=DARK, padx=18)
        tk.Label(self._session_row, text='Scan session:',
                 bg=DARK, fg=MGRAY, font=FONT_SMALL).pack(side='left', padx=(0, 8))
        self._session_var = tk.StringVar(value='')
        self._session_menu = tk.OptionMenu(self._session_row, self._session_var, '')
        self._session_menu.config(bg=PANEL, fg=WHITE, activebackground=TEAL,
                                  font=FONT_SMALL, relief='flat', bd=0)
        self._session_menu['menu'].config(bg=PANEL, fg=WHITE, font=FONT_SMALL)
        self._session_menu.pack(side='left')
        # starts hidden
        self._sessions: list[dict] = []
        self._scan_index: int = 0

        # ── Missing-XPS instruction box ──────────────────────────────────────
        self._instruct_frame = tk.Frame(self, bg='#1a1a00', padx=14, pady=10)
        self._instruct_var   = tk.StringVar(value='')
        self._instruct_lbl   = tk.Label(
            self._instruct_frame, textvariable=self._instruct_var,
            bg='#1a1a00', fg='#FFD54F', font=FONT_SMALL,
            justify='left', wraplength=580, anchor='nw',
        )
        self._instruct_lbl.pack(anchor='w')

        # ── Log / progress area ──────────────────────────────────────────────
        log_frame = tk.Frame(self, bg=DARK, padx=18)
        log_frame.pack(fill='both', expand=True, pady=(6, 0))

        self._log_text = tk.Text(
            log_frame, height=8, bg='#080e18', fg='#90CAF9',
            font=FONT_MONO, relief='flat', state='disabled',
            wrap='word', insertbackground=WHITE,
        )
        self._log_text.pack(fill='both', expand=True)

        # ── Status bar ───────────────────────────────────────────────────────
        self._status_var = tk.StringVar(value='Initialising…')
        status_bar = tk.Frame(self, bg=PANEL, height=33)
        status_bar.pack(fill='x')
        status_bar.pack_propagate(False)
        tk.Label(status_bar, textvariable=self._status_var,
                 bg=PANEL, fg=LGRAY, font=FONT_SMALL, anchor='w').pack(
            side='left', padx=10)

        # ── Button row ───────────────────────────────────────────────────────
        btn_frame = tk.Frame(self, bg=DARK, height=84)
        btn_frame.pack(fill='x')
        btn_frame.pack_propagate(False)

        self._collect_btn = tk.Button(
            btn_frame,
            text='▲   Collect Scan Data',
            bg=TEAL, fg=WHITE,
            activebackground=TEAL_LT, activeforeground=WHITE,
            font=('Helvetica', 17, 'bold'), relief='flat',
            padx=33, pady=15, cursor='hand2',
            state='disabled',
            command=self._on_collect,
        )
        self._collect_btn.pack(side='left', padx=14, pady=8)

        tk.Button(
            btn_frame, text='Exit',
            bg=DARK, fg=MGRAY,
            activebackground='#1a2f45', activeforeground=WHITE,
            font=FONT_BODY, relief='flat', padx=12, pady=10,
            command=self._on_close,
        ).pack(side='right', padx=14, pady=8)

    # ─── XPS row builder ─────────────────────────────────────────────────────

    _OSTEO_LABELS = [
        ('spine',       'Spine (AP)'),
        ('left_femur',  'Left Femur'),
        ('right_femur', 'Right Femur'),
    ]
    _TB_LABELS = [
        ('bone',        'Bone Density'),
        ('composition', 'Composition'),
    ]

    def _build_xps_rows(self, mode: str):
        """Destroy existing XPS rows and rebuild for the given mode."""
        for w in self._xps_frame.winfo_children():
            w.destroy()
        self._xps_rows = {}
        labels = self._TB_LABELS if mode == 'total_body' else self._OSTEO_LABELS
        for key, title in labels:
            row_frame = tk.Frame(self._xps_frame, bg=PANEL, padx=10, pady=6,
                                 highlightthickness=1, highlightbackground='#1a3a55')
            row_frame.pack(fill='x', pady=2)
            dot = tk.Label(row_frame, text='●', fg=MGRAY, bg=PANEL,
                           font=('Helvetica', 24), width=2)
            dot.pack(side='left')
            tk.Label(row_frame, text=title, bg=PANEL, fg=WHITE,
                     font=FONT_LABEL, width=16, anchor='w').pack(side='left')
            path_lbl = tk.Label(row_frame, text='—', bg=PANEL, fg=LGRAY,
                                font=FONT_MONO, anchor='w')
            path_lbl.pack(side='left', fill='x', expand=True)
            self._xps_rows[key] = {'dot': dot, 'path_lbl': path_lbl, 'frame': row_frame}

    # ─── Patient loading ──────────────────────────────────────────────────────

    def _load_patient(self, mrn: Optional[str] = None):
        self._set_status('Reading MDB…')
        self._collect_btn.config(state='disabled')

        try:
            if mrn:
                info = get_patient_by_mrn(mrn)
                if not info:
                    self._name_var.set(f'MRN {mrn} not found in MDB')
                    self._meta_var.set('')
                    self._set_status(f'Patient {mrn} not found.')
                    self._update_xps_panel({})
                    return
            else:
                info = get_latest_patient()
                if not info:
                    self._name_var.set('No recent patients in MDB')
                    self._meta_var.set('Ensure MDB_PATH in config is correct and a scan exists within 72 hrs.')
                    self._set_status('No patients found (last 72 hrs).')
                    self._update_xps_panel({})
                    return
        except Exception as e:
            self._log(f"ERROR reading MDB: {e}")
            self._set_status('MDB error — check config.py')
            self._name_var.set('Error reading MDB')
            return

        self._patient = info
        self._xps_map = info['xps_status']['found']
        self._scan_date = info.get('scan_date')
        self._scan_index = 0

        # Fetch all sessions so staff can pick an older one
        try:
            sessions = get_sessions_for_mrn(info['mrn'])
        except Exception:
            sessions = []
        self._sessions = sessions

        # Update patient card
        sd = info['scan_date']
        date_str = sd.strftime('%d %b %Y  %H:%M') if isinstance(sd, datetime) else str(sd)
        self._name_var.set(info['name'] or '(name not set)')
        self._meta_var.set(
            f"MRN: {info['mrn']}   •   Scan: {date_str}   •   Scanner: {config.SCANNER_ID}"
        )

        # Populate session dropdown if there are multiple scans
        if len(sessions) > 1:
            labels = []
            for s in sessions:
                d = s['scan_date']
                labels.append(d.strftime('%d %b %Y  %H:%M') if isinstance(d, datetime) else str(d))
            self._session_var.set(labels[0])
            menu = self._session_menu['menu']
            menu.delete(0, 'end')
            for i, lbl in enumerate(labels):
                menu.add_command(
                    label=lbl,
                    command=lambda idx=i, l=lbl: self._on_session_select(idx, l),
                )
            self._session_row.pack(fill='x', padx=16, pady=(0, 4))
        else:
            self._session_row.pack_forget()

        # Detect scan type: check for total body XPS first, fall back to osteo
        mrn = info['mrn']
        tb_found = detect_totalbody_xps(mrn=mrn, scan_date=self._scan_date)
        if tb_found:
            self._scan_mode = 'total_body'
            st = tb_xps_status(mrn=mrn, scan_date=self._scan_date)
        else:
            self._scan_mode = 'osteo'
            st = xps_status(scan_date=self._scan_date, mrn=mrn)
        self._xps_map = st['found']
        self.after(0, lambda _st=st: self._update_xps_panel(_st))

    def _update_xps_panel(self, st: dict):
        # Rebuild rows if mode changed
        mode = self._scan_mode
        expected_keys = {'bone', 'composition'} if mode == 'total_body' else {'spine', 'left_femur', 'right_femur'}
        if set(self._xps_rows.keys()) != expected_keys:
            self._build_xps_rows(mode)

        badge = '🦴  TOTAL BODY SCAN' if mode == 'total_body' else '🦷  OSTEO SCAN'
        self._mode_badge_var.set(badge)
        btn_label = '▲   Collect Total Body' if mode == 'total_body' else '▲   Collect Scan Data'
        self._collect_btn.config(text=btn_label)

        found   = st.get('found', {})
        missing = st.get('missing', [])
        ready   = st.get('ready', False)

        for key, widgets in self._xps_rows.items():
            if key in found:
                fname = Path(found[key]).name
                widgets['dot'].config(fg=GREEN_L, text='●')
                widgets['path_lbl'].config(fg='#4FC3F7', text=fname)
                widgets['frame'].config(highlightbackground='#1a5a2a')
            else:
                widgets['dot'].config(fg=RED_L, text='✗')
                widgets['path_lbl'].config(fg=RED_L, text='Not found in XPS folder')
                widgets['frame'].config(highlightbackground='#5a1a1a')

        # Instructions
        if missing and not ready:
            watch = config.XPS_WATCH_DIR
            human = {'spine': 'Spine', 'left_femur': 'Left Femur', 'right_femur': 'Right Femur'}
            names = ', '.join(human[m] for m in missing)
            msg = (
                f"⚠  Missing: {names}\n\n"
                f"In GE Lunar: open the scan → File → Save As → XPS Document\n"
                f"Save to the XPS folder:  {watch}\n\n"
                f"Then click ⟳ Refresh to re-check."
            )
            self._instruct_var.set(msg)
            self._instruct_frame.pack(fill='x', padx=0, pady=(4, 0))
        else:
            self._instruct_frame.pack_forget()

        # Button state
        if ready and self._patient:
            self._collect_btn.config(state='normal')
            self._set_status('Ready — click "Collect Scan Data" to upload.')
        else:
            self._collect_btn.config(state='disabled')
            if missing:
                self._set_status(f'{len(missing)} XPS file(s) missing — see instructions above.')
            else:
                self._set_status('No patient loaded.')

    def _load_by_mrn(self):
        mrn = self._mrn_entry.get().strip()
        if not mrn:
            mb.showwarning('MRN required', 'Enter a patient MRN first.')
            return
        self._name_var.set('Loading…')
        self._meta_var.set('')
        threading.Thread(target=self._load_patient, args=(mrn,), daemon=True).start()

    def _on_session_select(self, idx: int, label: str):
        self._scan_index = idx
        self._session_var.set(label)
        sd = self._sessions[idx]['scan_date']
        date_str = sd.strftime('%d %b %Y  %H:%M') if isinstance(sd, datetime) else str(sd)
        self._meta_var.set(
            f"MRN: {self._patient['mrn']}   •   Scan: {date_str}   •   Scanner: {config.SCANNER_ID}"
        )

    # ─── Upload ───────────────────────────────────────────────────────────────

    def _on_collect(self):
        if self._uploading or not self._patient:
            return
        mrn = self._patient['mrn']
        if not mrn:
            mb.showerror('No MRN', 'Patient has no MRN set in GE Lunar. Cannot upload.')
            return

        self._uploading = True
        self._collect_btn.config(state='disabled', text='Uploading…')
        self._log(f"=== Collecting scan for MRN {mrn} ===")

        mode = self._scan_mode

        def _run():
            try:
                if mode == 'total_body':
                    upload_totalbody_scan(mrn, self._xps_map,
                                         progress_cb=self._log)
                else:
                    upload_osteo_scan(mrn, self._xps_map,
                                      progress_cb=self._log,
                                      scan_index=self._scan_index)
                self.after(0, self._on_success)
            except Exception as e:
                log.exception("Upload failed: %s", e)
                self.after(0, lambda: self._on_error(str(e)))

        threading.Thread(target=_run, daemon=True).start()

    def _on_success(self):
        self._uploading = False
        self._collect_btn.config(text='▲   Collect Scan Data')
        self._set_status('Upload complete ✓')
        self._log("=== Upload successful ===")

        # Offer to clear the XPS staging folder so next patient starts clean
        xps_paths = list(self._xps_map.values())
        msg = (
            f"Scan data for {self._patient['name']} uploaded to Supabase.\n\n"
            "The Ubuntu server will generate the PDF on demand.\n\n"
            f"Clear the {len(xps_paths)} uploaded XPS file(s) from the watch folder?\n"
            "(Recommended — prevents them being picked up for the next patient.)"
        )
        if xps_paths and mb.askyesno('Upload Complete', msg, default='yes'):
            n = clear_xps_watch_folder(paths_to_delete=xps_paths)
            self._log(f"Cleared {n} XPS file(s) from watch folder.")
            self._set_status(f'Upload complete ✓ — {n} XPS file(s) cleared.')
        else:
            mb.showinfo(
                'Upload Complete',
                f"Scan data for {self._patient['name']} uploaded.\n\n"
                "The Ubuntu server will generate the PDF on demand."
            )

    def _on_error(self, msg: str):
        self._uploading = False
        self._collect_btn.config(state='normal', text='▲   Collect Scan Data')
        self._set_status('Upload FAILED — see log.')
        self._log(f"ERROR: {msg}")
        mb.showerror('Upload Failed', msg)

    # ─── Helpers ─────────────────────────────────────────────────────────────

    def _log(self, msg: str):
        def _append():
            self._log_text.config(state='normal')
            ts = datetime.now().strftime('%H:%M:%S')
            self._log_text.insert('end', f"[{ts}] {msg}\n")
            self._log_text.see('end')
            self._log_text.config(state='disabled')
        self.after(0, _append)

    def _set_status(self, msg: str):
        self.after(0, lambda: self._status_var.set(msg))

    def _on_close(self):
        if self._uploading:
            if not mb.askyesno('Uploading', 'An upload is in progress. Exit anyway?'):
                return
        self.destroy()


# ─── Entry point ──────────────────────────────────────────────────────────────

def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s: %(message)s',
    )
    app = OsteoCollectorApp()
    app.mainloop()


if __name__ == '__main__':
    main()
