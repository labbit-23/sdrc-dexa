"""
SDRC Data Collector — Windows UI.

Minimal tkinter window that:
  1. Shows recent patients from MDB with XPS detection status
  2. [Gather Data] — scans MDB + finds XPS files
  3. [Browse] — lets operator manually locate a missing XPS
  4. [Upload & Done] — uploads raw MDB snapshot + XPS to Supabase

Run on Windows:
  pythonw.exe collector_ui.py

Requires: Python 3.8+, tkinter (bundled), collect.py, sync_supabase.py
No pipeline, no PDF generation, no heavy imports.
"""

import logging
import threading
import tkinter as tk
import tkinter.filedialog as fd
import tkinter.messagebox as mb
from datetime import datetime
from pathlib import Path

import config
from collect import get_recent_patients, find_xps_for_patient, upload_patient_raw

log = logging.getLogger(__name__)

# ── Colours ──────────────────────────────────────────────────────────────────
TEAL    = '#0D7377'
DARK    = '#0D1B2A'
WHITE   = '#FFFFFF'
LGRAY   = '#F5F5F5'
MGRAY   = '#9E9E9E'
GREEN   = '#2E7D32'
AMBER   = '#E65100'
RED     = '#B71C1C'
PINK    = '#E91E8C'


class CollectorApp(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title('SDRC Data Collector')
        self.geometry('720x520')
        self.resizable(False, False)
        self.configure(bg=DARK)

        # State: list of patient dicts (from collect.get_recent_patients)
        self._patients: list[dict] = []
        # Per-patient extra XPS files added via Browse
        self._extra_xps: dict[str, list[str]] = {}
        # Per-patient upload status
        self._uploaded: set[str] = set()

        self._build_ui()
        self.after(200, self._gather)   # auto-gather on open

    # ── UI construction ───────────────────────────────────────────────────

    def _build_ui(self):
        # Header bar
        hdr = tk.Frame(self, bg=TEAL, height=48)
        hdr.pack(fill='x')
        hdr.pack_propagate(False)
        tk.Label(hdr, text='SDRC  DATA  COLLECTOR', bg=TEAL, fg=WHITE,
                 font=('Helvetica', 14, 'bold')).pack(side='left', padx=16, pady=12)
        tk.Label(hdr, text=config.CLINIC_NAME, bg=TEAL, fg='#B2DFDB',
                 font=('Helvetica', 9)).pack(side='right', padx=16, pady=16)

        # Patient list frame
        list_frame = tk.Frame(self, bg=DARK)
        list_frame.pack(fill='both', expand=True, padx=10, pady=(8, 0))

        tk.Label(list_frame, text='Recent patients (last 48 hrs)',
                 bg=DARK, fg=MGRAY, font=('Helvetica', 8)).pack(anchor='w')

        # Scrollable canvas for patient rows
        self._canvas = tk.Canvas(list_frame, bg=DARK, highlightthickness=0)
        scrollbar = tk.Scrollbar(list_frame, orient='vertical',
                                 command=self._canvas.yview)
        self._scroll_frame = tk.Frame(self._canvas, bg=DARK)
        self._scroll_frame.bind('<Configure>',
            lambda e: self._canvas.configure(
                scrollregion=self._canvas.bbox('all')))
        self._canvas.create_window((0, 0), window=self._scroll_frame, anchor='nw')
        self._canvas.configure(yscrollcommand=scrollbar.set)
        self._canvas.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')

        # Status bar
        self._status_var = tk.StringVar(value='Click Gather Data to scan MDB…')
        status_bar = tk.Frame(self, bg=DARK, height=24)
        status_bar.pack(fill='x')
        tk.Label(status_bar, textvariable=self._status_var,
                 bg=DARK, fg=MGRAY, font=('Helvetica', 8),
                 anchor='w').pack(side='left', padx=12)

        # Button row
        btn_frame = tk.Frame(self, bg=DARK, height=52)
        btn_frame.pack(fill='x')
        btn_frame.pack_propagate(False)

        self._gather_btn = tk.Button(
            btn_frame, text='⟳  Gather Data',
            bg=TEAL, fg=WHITE, activebackground='#0D9498', activeforeground=WHITE,
            font=('Helvetica', 10, 'bold'), relief='flat', padx=18, pady=8,
            command=lambda: threading.Thread(target=self._gather, daemon=True).start(),
        )
        self._gather_btn.pack(side='left', padx=12, pady=8)

        self._upload_btn = tk.Button(
            btn_frame, text='↑  Upload & Done',
            bg=GREEN, fg=WHITE, activebackground='#1B5E20', activeforeground=WHITE,
            font=('Helvetica', 10, 'bold'), relief='flat', padx=18, pady=8,
            state='disabled',
            command=lambda: threading.Thread(target=self._upload_all, daemon=True).start(),
        )
        self._upload_btn.pack(side='left', padx=4, pady=8)

        tk.Button(
            btn_frame, text='Exit',
            bg=DARK, fg=MGRAY, activebackground='#1a2f45', activeforeground=WHITE,
            font=('Helvetica', 9), relief='flat', padx=12, pady=8,
            command=self.destroy,
        ).pack(side='right', padx=12, pady=8)

    # ── Patient row rendering ─────────────────────────────────────────────

    def _render_rows(self):
        for w in self._scroll_frame.winfo_children():
            w.destroy()

        if not self._patients:
            tk.Label(self._scroll_frame, text='No recent patients found in MDB.',
                     bg=DARK, fg=MGRAY, font=('Helvetica', 9),
                     pady=20).pack()
            return

        any_uploadable = False

        for info in self._patients:
            patient  = info['patient']
            pid      = patient.get('patient_id', '')
            name     = f"{patient.get('title','')} {patient.get('name','')}".strip()
            sd       = info.get('scan_date')
            date_str = sd.strftime('%d %b %Y  %H:%M') if sd else '—'

            xps_list = list(info['xps_files']) + self._extra_xps.get(pid, [])
            has_xps  = bool(xps_list)
            uploaded = pid in self._uploaded

            # Row card
            card_bg = '#0a2a1a' if uploaded else ('#1a2f45' if has_xps else '#2a1010')
            row = tk.Frame(self._scroll_frame, bg=card_bg,
                           highlightbackground='#1a3a55', highlightthickness=1)
            row.pack(fill='x', padx=4, pady=3)

            # Status dot
            dot_col = GREEN if uploaded else (TEAL if has_xps else RED)
            dot_lbl = '●' if not uploaded else '✓'
            tk.Label(row, text=dot_lbl, bg=card_bg, fg=dot_col,
                     font=('Helvetica', 14), width=2).pack(side='left', padx=6)

            # Patient info
            info_frame = tk.Frame(row, bg=card_bg)
            info_frame.pack(side='left', fill='both', expand=True, pady=6)
            tk.Label(info_frame, text=name, bg=card_bg, fg=WHITE,
                     font=('Helvetica', 10, 'bold'), anchor='w').pack(anchor='w')
            tk.Label(info_frame,
                     text=f"ID: {pid}   Scan: {date_str}",
                     bg=card_bg, fg=MGRAY,
                     font=('Helvetica', 8), anchor='w').pack(anchor='w')

            # XPS status
            xps_frame = tk.Frame(row, bg=card_bg)
            xps_frame.pack(side='left', padx=12)
            if uploaded:
                tk.Label(xps_frame, text='Uploaded ✓', bg=card_bg,
                         fg=GREEN, font=('Helvetica', 8, 'bold')).pack()
            elif has_xps:
                for xp in xps_list:
                    tk.Label(xps_frame, text=f'✓ {Path(xp).name}',
                             bg=card_bg, fg='#4FC3F7',
                             font=('Helvetica', 7)).pack(anchor='w')
                any_uploadable = True
            else:
                tk.Label(xps_frame, text='✗  XPS not found',
                         bg=card_bg, fg=RED,
                         font=('Helvetica', 8, 'bold')).pack()

            # Browse button (shown when XPS missing and not yet uploaded)
            if not has_xps and not uploaded:
                browse_btn = tk.Button(
                    row, text='Browse…',
                    bg=AMBER, fg=WHITE, relief='flat',
                    font=('Helvetica', 8), padx=8, pady=4,
                    command=lambda p=pid, i=info: self._browse_xps(p, i),
                )
                browse_btn.pack(side='right', padx=8)
            else:
                tk.Frame(row, bg=card_bg, width=80).pack(side='right')

        self._upload_btn.config(state='normal' if any_uploadable else 'disabled')

    # ── Actions ───────────────────────────────────────────────────────────

    def _set_status(self, msg: str):
        self._status_var.set(msg)
        self.update_idletasks()

    def _gather(self):
        self._set_status('Scanning MDB…')
        self._gather_btn.config(state='disabled')
        try:
            self._patients = get_recent_patients(hours=48)
            self._extra_xps = {}
            count = len(self._patients)
            missing = sum(1 for p in self._patients if p['xps_missing'])
            self._set_status(
                f'Found {count} patient(s) — '
                f'{count - missing} with XPS, {missing} missing.'
            )
        except Exception as e:
            self._set_status(f'Error reading MDB: {e}')
            log.exception("Gather failed: %s", e)
        finally:
            self._gather_btn.config(state='normal')
            self.after(0, self._render_rows)

    def _browse_xps(self, patient_id: str, info: dict):
        paths = fd.askopenfilenames(
            title=f'Select XPS file(s) for patient {patient_id}',
            filetypes=[('XPS files', '*.xps'), ('All files', '*.*')],
        )
        if paths:
            self._extra_xps.setdefault(patient_id, []).extend(paths)
            info['xps_files'] = list(paths)
            info['xps_missing'] = False
            self.after(0, self._render_rows)

    def _upload_all(self):
        self._upload_btn.config(state='disabled')
        self._gather_btn.config(state='disabled')

        errors = []
        for info in self._patients:
            pid = info['patient'].get('patient_id', '')
            if pid in self._uploaded:
                continue
            xps_list = list(info['xps_files']) + self._extra_xps.get(pid, [])
            if not xps_list:
                continue  # skip patients with no XPS

            try:
                def _cb(msg, p=pid):
                    self._set_status(f'[{p}] {msg}')

                upload_patient_raw(pid, xps_list, progress_cb=_cb)
                self._uploaded.add(pid)
            except Exception as e:
                log.exception("Upload failed for %s: %s", pid, e)
                errors.append(f'{pid}: {e}')

        self.after(0, self._render_rows)
        self._gather_btn.config(state='normal')

        if errors:
            mb.showerror('Upload errors', '\n'.join(errors))
            self._set_status('Some uploads failed — see error dialog.')
        else:
            self._set_status(
                f'All done — {len(self._uploaded)} patient(s) uploaded to Supabase.'
            )


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s: %(message)s',
    )
    app = CollectorApp()
    app.mainloop()


if __name__ == '__main__':
    main()
