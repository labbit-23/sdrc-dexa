"""
Windows system-tray icon for SDRC Report Generator.

Starts the watcher in a background thread.
Menu allows manual report generation and opening the web frontend.

Run at startup via Task Scheduler:
  pythonw.exe tray_app.py
"""

import sys
import threading
import webbrowser
import logging
import tkinter as tk
import tkinter.simpledialog as sd

import pystray
from PIL import Image as PILImage, ImageDraw

import config
import watcher
from pipeline import run_pipeline_for_patient, run_pipeline_xps

log = logging.getLogger(__name__)

_stop_event = threading.Event()
_watcher_thread = None


# ── Tray icon image ────────────────────────────────────────────────────────
def _make_icon_image() -> PILImage.Image:
    """Create a simple 64×64 teal square with 'SD' text."""
    img = PILImage.new('RGBA', (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, 63, 63], fill='#0D7377', outline='#0D9498', width=2)
    draw.text((12, 18), 'SD', fill='white')
    draw.text((10, 32), 'RC', fill='white')
    return img


# ── Menu actions ───────────────────────────────────────────────────────────
def _action_latest(icon, item):
    """Generate report for the most recently modified XPS in the watch folder."""
    def _run():
        from pathlib import Path
        xps_files = sorted(
            Path(config.XPS_WATCH_DIR).glob('*.xps'),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        if not xps_files:
            _notify(icon, "No XPS files found in watch folder.")
            return
        xps_path = str(xps_files[0])
        _notify(icon, f"Generating report for {xps_files[0].name}…")
        result = run_pipeline_xps(xps_path, upload=True)
        if result:
            _notify(icon, "Report generated and synced.")
        else:
            _notify(icon, "Report generation failed — check logs.")
    threading.Thread(target=_run, daemon=True).start()


def _action_by_patient(icon, item):
    """Prompt for patient ID and generate their latest report."""
    def _run():
        root = tk.Tk()
        root.withdraw()
        pid = sd.askstring("SDRC Report Generator", "Enter Patient ID:")
        root.destroy()
        if not pid:
            return
        pid = pid.strip()
        _notify(icon, f"Generating report for patient {pid}…")
        result = run_pipeline_for_patient(pid, upload=True)
        if result:
            _notify(icon, f"Report for {pid} generated.")
        else:
            _notify(icon, f"No scan found for patient {pid}.")
    threading.Thread(target=_run, daemon=True).start()


def _action_open_frontend(icon, item):
    webbrowser.open(config.FRONTEND_URL)


def _action_exit(icon, item):
    _stop_event.set()
    icon.stop()


def _notify(icon, message: str):
    try:
        icon.notify(message, "SDRC Report Generator")
    except Exception:
        log.info("Notification: %s", message)


# ── Main ──────────────────────────────────────────────────────────────────
def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s: %(message)s',
        filename=config.OUTPUT_PDF_DIR + r'\sdrc_worker.log',
    )
    log.info("Tray app starting")

    # Start watcher in background
    global _watcher_thread
    _watcher_thread = threading.Thread(
        target=watcher.poll_loop,
        args=(_stop_event,),
        daemon=True,
        name='watcher',
    )
    _watcher_thread.start()

    icon_img = _make_icon_image()
    menu = pystray.Menu(
        pystray.MenuItem('Generate Latest Report',   _action_latest),
        pystray.MenuItem('Generate for Patient ID…', _action_by_patient),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem('Open Web Frontend',        _action_open_frontend),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem('Exit',                     _action_exit),
    )
    icon = pystray.Icon(
        'SDRC',
        icon_img,
        'SDRC Report Generator — Running',
        menu,
    )
    icon.run()


if __name__ == '__main__':
    main()
