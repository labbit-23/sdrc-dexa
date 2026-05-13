"""
XPS directory watcher.

Polls XPS_WATCH_DIR every POLL_INTERVAL seconds.
When a new (or replaced) .xps file appears, runs the full pipeline.

File identity = (absolute path, mtime).  If staff saves a corrected version
of the same filename the mtime changes and it gets re-processed.

patient_id is extracted from the filename stem: everything before the first '-'.
  e.g.  20260323063-spine.xps       → patient_id 20260323063
        20260323063-spine-v2.xps    → patient_id 20260323063
        20260323063.xps             → patient_id 20260323063
"""

import logging
import sqlite3
import time
from pathlib import Path
from datetime import datetime

import config
from pipeline import run_pipeline_xps, reload_parser

log = logging.getLogger(__name__)


# ── SQLite dedup store ────────────────────────────────────────────────────
def _init_db() -> sqlite3.Connection:
    con = sqlite3.connect(config.PROCESSED_DB)
    con.execute("""
        create table if not exists xps_done (
            path     text primary key,
            mtime    real not null,
            ts       text,
            status   text,
            xps_type text
        )
    """)
    # Legacy table kept for backward compatibility
    con.execute(
        "create table if not exists done "
        "(handle text primary key, ts text, status text)"
    )
    con.commit()
    return con


def _known(con: sqlite3.Connection) -> dict[str, float]:
    """Return {filepath: mtime} for every already-processed XPS."""
    return {row[0]: row[1] for row in con.execute("select path, mtime from xps_done")}


def _mark(con: sqlite3.Connection, path: str, mtime: float,
          status: str = 'ok', xps_type: str = '') -> None:
    con.execute(
        "insert or replace into xps_done values (?,?,?,?,?)",
        (path, mtime, datetime.utcnow().isoformat(), status, xps_type),
    )
    con.commit()


# ── Directory scan ────────────────────────────────────────────────────────
def _scan_dir(known: dict[str, float]) -> list[tuple[str, float]]:
    """Return [(path, mtime)] for XPS files that are new or have changed."""
    watch = Path(config.XPS_WATCH_DIR)
    new = []
    for f in watch.glob('*.xps'):
        p = str(f.resolve())
        mtime = f.stat().st_mtime
        prev = known.get(p)
        if prev is None or abs(mtime - prev) > 1.0:
            new.append((p, mtime))
    return new


# ── Poll loop ─────────────────────────────────────────────────────────────
def poll_loop(stop_event=None):
    """
    Main polling loop.  Runs forever (or until stop_event is set).
    stop_event: threading.Event (optional)
    """
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    )
    log.info("Watcher starting — watching %s every %ds",
             config.XPS_WATCH_DIR, config.POLL_INTERVAL)

    con     = _init_db()
    known   = _known(con)

    while True:
        if stop_event and stop_event.is_set():
            log.info("Watcher stopping")
            break

        try:
            reload_parser()
            new_files = _scan_dir(known)
            log.info("Poll: %d new/changed XPS file(s)", len(new_files))

            for xps_path, mtime in new_files:
                fname = Path(xps_path).name
                log.info("Processing: %s", fname)
                try:
                    result = run_pipeline_xps(xps_path, upload=True)
                    status = 'ok' if result else 'skipped'
                except Exception as e:
                    log.exception("Pipeline failed for %s: %s", fname, e)
                    status = 'error'

                _mark(con, xps_path, mtime, status=status)
                known[xps_path] = mtime

        except Exception as e:
            log.exception("Poll loop error: %s", e)

        for _ in range(config.POLL_INTERVAL):
            if stop_event and stop_event.is_set():
                break
            time.sleep(1)


if __name__ == '__main__':
    poll_loop()
