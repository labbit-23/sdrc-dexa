"""
XPS parser for GE Lunar DPX DEXA reports.

Extracts:
  1. BMD / T-score / Z-score text from the fpage XML (authoritative values)
  2. Scan images (spine, left femur, right femur) with false-colour processing

Image strip assignments verified against actual SDRC XPS files:
  Strips  1– 9  → AP Spine
  Strips 10–18  → Left Femur
  Strips 19–29  → Right Femur
"""

import zipfile
import re
import io
import logging
import subprocess
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image

log = logging.getLogger(__name__)


# ── XPS page rendering (requires mupdf-tools: apt install mupdf-tools) ────────
def render_xps_pages(xps_path: str, dpi: int = 150) -> list[bytes]:
    """
    Render every page of an XPS file to PNG using mutool (mupdf-tools).
    Returns a list of PNG bytes, one per page, in page order.
    Returns [] if mutool is unavailable or fails.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        out_pat = str(Path(tmpdir) / "page%d.png")
        try:
            r = subprocess.run(
                ["mutool", "draw", "-r", str(dpi), "-o", out_pat, xps_path],
                capture_output=True, text=True, timeout=60,
            )
            if r.returncode != 0:
                log.warning("mutool draw failed for %s: %s", xps_path, r.stderr[:200])
                return []
        except FileNotFoundError:
            log.warning("mutool not found — install mupdf-tools for overlay images")
            return []
        except subprocess.TimeoutExpired:
            log.warning("mutool timed out on %s", xps_path)
            return []

        pages: list[bytes] = []
        i = 1
        while True:
            p = Path(tmpdir) / f"page{i}.png"
            if not p.exists():
                break
            pages.append(p.read_bytes())
            i += 1
        log.info("render_xps_pages: %d page(s) from %s", len(pages), Path(xps_path).name)
        return pages


def _parse_all_strip_bounds(xps_path: str) -> dict[str, tuple[float, float, float, float]]:
    """
    Parse the fpage XAML and return crop bounds (in XPS units) for each scan region
    by grouping ImageBrush Viewports by strip number.

    GE Lunar strip assignments (verified for combined XPS):
      Strips  1– 9  → 'spine'
      Strips 10–18  → 'left_femur'
      Strips 19–28  → 'right_femur'   (strip 29 = RGBA colour-scale bar, excluded)

    Note: Position-based region detection (_parse_zone_region) is preferred;
    hardcoded ranges below are fallback only. Forearm regions detected via
    "Densitometry Reference:" labels in XAML text, not strip numbers.

    Returns dict with keys from the above set, only for regions that have strips.
    Values are (x1, y1, x2, y2) in XPS units with a small margin.
    """
    _STRIP_REGIONS = {
        'spine':       range(1, 10),
        'left_femur':  range(10, 19),
        'right_femur': range(19, 29),  # strip 29 is the colour-scale bar (RGBA, Y≈979)
    }

    try:
        with zipfile.ZipFile(xps_path) as z:
            fpage = z.read("Documents/1/Pages/1.fpage").decode("utf-8", errors="replace")
    except Exception:
        return {}

    # Match ImageBrush elements referencing Images/N.PNG, capturing strip number + Viewport.
    # Two alternates handle either attribute order; groups: (1,2,3,4,5) or (6,7,8,9,10)
    #   ImageSource first: group 1=strip_num, 2=x, 3=y, 4=w, 5=h
    #   Viewport first:    group 6=x, 7=y, 8=w, 9=h, 10=strip_num
    strip_re = re.compile(
        r'ImageSource="[^"]*Images/(\d+)\.PNG"[^/]*?Viewport="([\d.]+),([\d.]+),([\d.]+),([\d.]+)"'
        r'|'
        r'Viewport="([\d.]+),([\d.]+),([\d.]+),([\d.]+)"[^/]*?ImageSource="[^"]*Images/(\d+)\.PNG"',
        re.IGNORECASE | re.DOTALL,
    )

    region_boxes: dict[str, list[tuple[float, float, float, float]]] = {k: [] for k in _STRIP_REGIONS}

    for m in strip_re.finditer(fpage):
        if m.group(1):  # ImageSource came first
            num = int(m.group(1))
            x, y, w, h = float(m.group(2)), float(m.group(3)), float(m.group(4)), float(m.group(5))
        else:           # Viewport came first
            num = int(m.group(10))
            x, y, w, h = float(m.group(6)), float(m.group(7)), float(m.group(8)), float(m.group(9))
        if w < 5 or h < 2:
            continue
        for region, nums in _STRIP_REGIONS.items():
            if num in nums:
                region_boxes[region].append((x, y, x + w, y + h))
                break

    # Collect ALL "Image not for diagnosis" Y positions from the page.
    # GE Lunar Glyphs elements have a long Indices attribute (glyph data) between
    # OriginY and UnicodeString, so a short lookback window misses OriginY.
    # Instead: find the containing <Glyphs element start, then extract OriginY from it.
    all_disclaimer_ys = []
    for m in re.finditer(r'UnicodeString="[^"]*not\s+for\s+diagnosis[^"]*"', fpage, re.IGNORECASE):
        elem_start = fpage.rfind('<Glyphs', 0, m.start())
        if elem_start == -1:
            elem_start = max(0, m.start() - 8000)
        ctx = fpage[elem_start:m.start()]
        oys = re.findall(r'OriginY="([\d.]+)"', ctx)
        if oys:
            all_disclaimer_ys.append(float(oys[-1]))
    log.info("_parse_all_strip_bounds: found %d disclaimer Y positions: %s", len(all_disclaimer_ys), all_disclaimer_ys)

    result = {}
    left_margin  =  8   # expand left slightly
    right_margin = 20   # trim right (scale bar lives here)
    top_margin   = 40   # enough to capture ROI triangle apex above first strip
    for region, boxes in region_boxes.items():
        if not boxes:
            continue
        bx1 = min(b[0] for b in boxes)
        by1 = min(b[1] for b in boxes)
        bx2 = max(b[2] for b in boxes)
        by2 = max(b[3] for b in boxes)
        # Find the disclaimer belonging to THIS region: Y must be below the region's
        # top (by1) and within 300 units below the region's bottom (by2).
        local_disclaimers = [y for y in all_disclaimer_ys if y > by1 and y < by2 + 300]
        if local_disclaimers:
            local_cap = min(local_disclaimers) - 2
            if local_cap > by1 + 20:
                by2 = min(by2, local_cap)
        result[region] = (max(0, bx1 - left_margin), max(0, by1 - top_margin), bx2 - right_margin, by2 + 2)
        log.info("_parse_all_strip_bounds: %s → %d strips, bounds=%s cap_y=%s",
                 region, len(boxes), result[region], local_disclaimers or None)

    return result


def _parse_dual_femur_bounds(xps_path: str) -> dict[str, tuple[float, float, float, float]]:
    """
    Parse crop bounds for a dual-femur-only XPS.

    Verified strip assignments for GE Lunar dual-femur XPS (39083.xps):
      Strips  1– 8  → left_femur   (Y ≈ 253–365)
      Strips  9–17  → right_femur  (Y ≈ 497–625)
      Strip  18     → colour-scale bar (excluded)
    """
    _STRIP_REGIONS = {
        'left_femur':  range(1, 9),
        'right_femur': range(9, 18),
    }

    try:
        with zipfile.ZipFile(xps_path) as z:
            fpage = z.read("Documents/1/Pages/1.fpage").decode("utf-8", errors="replace")
    except Exception:
        return {}

    strip_re = re.compile(
        r'ImageSource="[^"]*Images/(\d+)\.PNG"[^/]*?Viewport="([\d.]+),([\d.]+),([\d.]+),([\d.]+)"'
        r'|'
        r'Viewport="([\d.]+),([\d.]+),([\d.]+),([\d.]+)"[^/]*?ImageSource="[^"]*Images/(\d+)\.PNG"',
        re.IGNORECASE | re.DOTALL,
    )

    region_boxes: dict[str, list[tuple[float, float, float, float]]] = {k: [] for k in _STRIP_REGIONS}
    for m in strip_re.finditer(fpage):
        if m.group(1):
            num = int(m.group(1))
            x, y, w, h = float(m.group(2)), float(m.group(3)), float(m.group(4)), float(m.group(5))
        else:
            num = int(m.group(10))
            x, y, w, h = float(m.group(6)), float(m.group(7)), float(m.group(8)), float(m.group(9))
        if w < 5 or h < 2:
            continue
        for region, nums in _STRIP_REGIONS.items():
            if num in nums:
                region_boxes[region].append((x, y, x + w, y + h))
                break

    left_margin  =  8
    right_margin = 20
    top_margin   = 40

    result = {}
    for region, boxes in region_boxes.items():
        if not boxes:
            continue
        x1 = min(b[0] for b in boxes)
        y1 = min(b[1] for b in boxes)
        x2 = max(b[2] for b in boxes)
        y2 = max(b[3] for b in boxes)
        result[region] = (max(0, x1 - left_margin), max(0, y1 - top_margin), x2 - right_margin, y2 + 2)
        log.info("_parse_dual_femur_bounds: %s → %d strips, bounds=%s", region, len(boxes), result[region])

    return result


# ── Position-based region extraction (replaces hardcoded strip ranges) ────────

_STRIP_VP_RE = re.compile(
    r'ImageSource="[^"]*Images/(\d+)\.PNG"[^/]*?Viewport="([\d.]+),([\d.]+),([\d.]+),([\d.]+)"'
    r'|'
    r'Viewport="([\d.]+),([\d.]+),([\d.]+),([\d.]+)"[^/]*?ImageSource="[^"]*Images/(\d+)\.PNG"',
    re.IGNORECASE | re.DOTALL,
)

_GLYPH_RE = re.compile(
    r'OriginX="([\d.]+)"\s+OriginY="([\d.]+)"\s+'
    r'(?:[A-Za-z]+="[^"]*"\s+)*?'
    r'Indices="[^"]*"\s+'
    r'UnicodeString="([^"]+)"',
)


def _collect_strip_viewports(xps_path: str) -> tuple[str, list[tuple[int, float, float, float, float]]]:
    """
    Open the XPS ZIP, identify valid scan strips (non-RGBA, h≥20, w≥100),
    parse their Viewport positions from all fpage XMLs, and return
    (combined_fpages_text, [(strip_num, x, y, x2, y2), ...]).

    Strips that appear at identical positions (same num+x+y) are deduplicated —
    GE Lunar reuses strip 1 as a header row in both hip columns.

    Reads from all pages in case of multi-page reports (e.g., page 1: spine/femur,
    page 2: forearm).
    """
    try:
        with zipfile.ZipFile(xps_path) as z:
            # Read all pages (not just page 1)
            fpage_texts = []
            for name in sorted(z.namelist()):
                if '/Pages/' in name and name.endswith('.fpage'):
                    try:
                        fpage_texts.append(z.read(name).decode("utf-8", errors="replace"))
                    except Exception:
                        pass

            if not fpage_texts:
                return '', []

            fpage = '\n'.join(fpage_texts)  # Combine all pages

            valid: set[int] = set()
            for name in z.namelist():
                if 'Images' not in name or not name.upper().endswith('.PNG'):
                    continue
                try:
                    num = int(name.split('/')[-1].split('.')[0])
                    img = Image.open(io.BytesIO(z.read(name)))
                    if img.mode != 'RGBA' and img.height >= 20 and img.width >= 100:
                        valid.add(num)
                except Exception:
                    pass
    except Exception:
        return '', []

    seen: set[tuple] = set()
    boxes: list[tuple[int, float, float, float, float]] = []
    for m in _STRIP_VP_RE.finditer(fpage):
        if m.group(1):
            num = int(m.group(1))
            x, y, w, h = float(m.group(2)), float(m.group(3)), float(m.group(4)), float(m.group(5))
        else:
            num = int(m.group(9))
            x, y, w, h = float(m.group(5)), float(m.group(6)), float(m.group(7)), float(m.group(8))
        if num not in valid or w < 5 or h < 2:
            continue
        key = (num, round(x, 1), round(y, 1))
        if key in seen:
            continue
        seen.add(key)
        boxes.append((num, x, y, x + w, y + h))

    return fpage, boxes


def _disclaimer_ys(fpage: str) -> list[float]:
    """Return Y positions of all 'Image not for diagnosis' glyphs, sorted ascending."""
    ys: list[float] = []
    for m in re.finditer(r'UnicodeString="[^"]*not\s+for\s+diagnosis[^"]*"', fpage, re.IGNORECASE):
        start = fpage.rfind('<Glyphs', 0, m.start())
        ctx = fpage[max(0, start if start != -1 else m.start() - 8000): m.start()]
        found = re.findall(r'OriginY="([\d.]+)"', ctx)
        if found:
            ys.append(float(found[-1]))
    return sorted(ys)


def _fpage_glyphs(fpage: str) -> list[tuple[float, float, str]]:
    """Extract all (x, y, text) glyph tuples from a fpage string."""
    return [
        (float(x), float(y), t.strip())
        for x, y, t in _GLYPH_RE.findall(fpage)
        if t.strip()
    ]


def _zone_region_name(
    glyphs: list[tuple[float, float, str]],
    y_search_lo: float,
    y_search_hi: float,
    used: set[str],
) -> str:
    """
    Classify a Y zone as 'spine', 'left_femur', 'right_femur', 'left_forearm', or 'right_forearm' by searching
    XAML glyph text between y_search_lo and y_search_hi.

    Looks for "Densitometry Reference:" lines (the most reliable anchor) first,
    then falls back to keyword presence near the zone boundary.
    Used names are skipped so each region is assigned at most once.
    """
    zone_text = ' '.join(
        t for _, y, t in glyphs
        if y_search_lo <= y <= y_search_hi
    ).lower()

    # "Densitometry Reference: AP Spine / Lumbar Spine" → spine
    if re.search(r'densitometry\s+reference[^.]{0,60}(?:ap\s+spine|lumbar)', zone_text):
        name = 'spine'
    # "Densitometry Reference: Left Forearm" → left_forearm
    elif re.search(r'densitometry\s+reference[^.]{0,60}left.*forearm', zone_text):
        name = 'left_forearm'
    # "Densitometry Reference: Right Forearm" → right_forearm
    elif re.search(r'densitometry\s+reference[^.]{0,60}right.*forearm', zone_text):
        name = 'right_forearm'
    # "Densitometry Reference: Left …" (femur) → left_femur
    elif re.search(r'densitometry\s+reference[^.]{0,60}left(?!.*forearm)', zone_text):
        name = 'left_femur'
    # "Densitometry Reference: Right …" (femur) → right_femur
    elif re.search(r'densitometry\s+reference[^.]{0,60}right(?!.*forearm)', zone_text):
        name = 'right_femur'
    # Broader keyword fallback
    elif re.search(r'\b(?:lumbar|ap\s+spine|l1[-–]l4)\b', zone_text) and 'spine' not in used:
        name = 'spine'
    elif re.search(r'\bleft\b', zone_text) and re.search(r'\b(?:forearm|radius|ulna)\b', zone_text) and 'left_forearm' not in used:
        name = 'left_forearm'
    elif re.search(r'\bright\b', zone_text) and re.search(r'\b(?:forearm|radius|ulna)\b', zone_text) and 'right_forearm' not in used:
        name = 'right_forearm'
    elif re.search(r'\bleft\b', zone_text) and re.search(r'\b(?:femur|proximal|hip|neck)\b', zone_text) and 'left_femur' not in used:
        name = 'left_femur'
    elif re.search(r'\bright\b', zone_text) and re.search(r'\b(?:femur|proximal|hip|neck)\b', zone_text) and 'right_femur' not in used:
        name = 'right_femur'
    else:
        # Pure positional fallback: spine → left_femur → right_femur → left_forearm → right_forearm
        for candidate in ('spine', 'left_femur', 'right_femur', 'left_forearm', 'right_forearm'):
            if candidate not in used:
                name = candidate
                break
        else:
            name = f'region_{len(used)}'

    return name if name not in used else f'region_{len(used)}'


def _dedup_strips_by_num(
    strip_boxes: list[tuple[int, float, float, float, float]],
) -> list[tuple[int, float]]:
    """
    Return [(strip_num, y_start), ...] sorted by Y, with each strip number
    appearing only once (earliest Y occurrence kept).

    GE Lunar reuses strip 1 as a shared header row in both hip columns of a
    side-by-side page; without deduplication it would be stitched twice.
    """
    seen: set[int] = set()
    result: list[tuple[int, float]] = []
    for b in sorted(strip_boxes, key=lambda b: b[2]):  # sort by y_start
        if b[0] not in seen:
            seen.add(b[0])
            result.append((b[0], b[2]))
    return result


def _x_gap_clusters(values: list[float], gap: float = 50.0) -> list[list[float]]:
    """Split a sorted list of floats into clusters separated by gaps > *gap*."""
    if not values:
        return []
    clusters: list[list[float]] = [[values[0]]]
    for v in sorted(values)[1:]:
        if v - clusters[-1][-1] > gap:
            clusters.append([])
        clusters[-1].append(v)
    return clusters


def _make_region_box(
    strip_boxes: list[tuple[int, float, float, float, float]],
    all_disc_ys: list[float],
) -> tuple[float, float, float, float]:
    """
    Build (x1, y1, x2, y2) bounding box exactly matching the strip Viewport extents.
    Bottom is capped just below the nearest 'Image not for diagnosis' disclaimer
    to exclude that text from the rendered overlay.
    No artificial margins — strips define the exact scan boundary.
    """
    x1 = min(b[1] for b in strip_boxes)
    y1 = min(b[2] for b in strip_boxes)
    x2 = max(b[3] for b in strip_boxes)
    y2 = max(b[4] for b in strip_boxes)

    local_disc = [d for d in all_disc_ys if d > y1 and d < y2 + 300]
    if local_disc:
        cap = min(local_disc) - 30
        if cap > y1 + 20:
            y2 = min(y2, cap)

    return (x1, y1, x2, y2)


def _parse_region_bounds_by_position(
    xps_path: str,
) -> dict[str, tuple[float, float, float, float]]:
    """
    Position-driven scan region extraction.  Replaces the hardcoded strip-number
    range tables in _parse_all_strip_bounds() and _parse_dual_femur_bounds().

    Works for all GE Lunar XPS formats used at SDRC:

    ┌─────────────────────┬──────────────────────────────────────────┐
    │ Format              │ Detection                                │
    ├─────────────────────┼──────────────────────────────────────────┤
    │ Stacked combined    │ Single X column, multiple Y zones        │
    │ (spine/L-hip/R-hip) │ separated by "Image not for diagnosis"   │
    │                     │ disclaimers                              │
    ├─────────────────────┼──────────────────────────────────────────┤
    │ Side-by-side hips   │ Two distinct X columns (gap > 50 units); │
    │ (L-hip | R-hip)     │ lower-X column → left_femur,             │
    │                     │ higher-X column → right_femur            │
    ├─────────────────────┼──────────────────────────────────────────┤
    │ Single scan         │ One X column, one Y zone                 │
    │ (spine only, etc.)  │                                          │
    └─────────────────────┴──────────────────────────────────────────┘

    Region names are inferred from "Densitometry Reference:" XAML text near
    each zone — no hardcoded strip numbers, no OCR.

    Returns {region_name: (x1, y1, x2, y2)} for each detected region.
    """
    fpage, strip_boxes = _collect_strip_viewports(xps_path)
    if not strip_boxes:
        log.warning("_parse_region_bounds_by_position: no valid strips in %s", xps_path)
        return {}

    disc_ys = _disclaimer_ys(fpage)
    log.info("_parse_region_bounds_by_position: %d strips, %d disclaimers Y=%s in %s",
             len(strip_boxes), len(disc_ys), disc_ys, Path(xps_path).name)

    # ── Layout detection ──────────────────────────────────────────────────────
    x_clusters = _x_gap_clusters([b[1] for b in strip_boxes], gap=50.0)

    if len(x_clusters) >= 2:
        # Side-by-side: multiple X columns — name each column from text below it
        return _region_bounds_sidebyside(strip_boxes, x_clusters, disc_ys, fpage)
    else:
        # Stacked: single X column, split by disclaimer Y zones
        return _region_bounds_stacked(strip_boxes, disc_ys, fpage)


def _region_bounds_sidebyside(
    strip_boxes: list[tuple[int, float, float, float, float]],
    x_clusters: list[list[float]],
    disc_ys: list[float],
    fpage: str,
) -> dict[str, tuple[float, float, float, float]]:
    """
    Side-by-side layout: assign each X column to a named region by reading the
    XAML glyph text below that column's scan strips — not by positional assumption.
    """
    sorted_clusters = sorted(x_clusters, key=lambda c: min(c))
    boundaries = [float('-inf')] + [
        (max(sorted_clusters[i]) + min(sorted_clusters[i + 1])) / 2
        for i in range(len(sorted_clusters) - 1)
    ] + [float('inf')]

    glyphs = _fpage_glyphs(fpage)
    used: set[str] = set()
    result: dict[str, tuple[float, float, float, float]] = {}

    for idx in range(len(sorted_clusters)):
        x_lo, x_hi = boundaries[idx], boundaries[idx + 1]
        col = [b for b in strip_boxes if x_lo < b[1] <= x_hi]
        if not col:
            continue
        col_y_bottom = max(b[4] for b in col)
        # Search text below this column for region identification
        name = _zone_region_name(glyphs, col_y_bottom - 10, col_y_bottom + 600, used)
        used.add(name)
        result[name] = _make_region_box(col, disc_ys)
        log.info("_region_bounds_sidebyside: %s → %d strips, box=%s", name, len(col), result[name])

    return result


def _region_bounds_stacked(
    strip_boxes: list[tuple[int, float, float, float, float]],
    disc_ys: list[float],
    fpage: str,
) -> dict[str, tuple[float, float, float, float]]:
    """
    Stacked layout: detect zones by Y-gap between consecutive strips (gap > 50 XPS units).
    Region names come from "Densitometry Reference:" text in the gap BEFORE each zone.
    """
    sorted_boxes = sorted(strip_boxes, key=lambda b: b[2])
    zones: list[list[tuple]] = []
    current: list[tuple] = []
    for b in sorted_boxes:
        if current and b[2] - max(c[4] for c in current) > 50:
            zones.append(current)
            current = []
        current.append(b)
    if current:
        zones.append(current)

    if not zones:
        return {}

    glyphs = _fpage_glyphs(fpage)
    used: set[str] = set()
    result: dict[str, tuple[float, float, float, float]] = {}

    for zi, zone in enumerate(zones):
        zone_y_top    = min(b[2] for b in zone)
        zone_y_bottom = max(b[4] for b in zone)
        # "Densitometry Reference:" label appears in the gap BEFORE each zone
        prev_bottom = max(b[4] for b in zones[zi - 1]) if zi > 0 else 0.0
        name = _zone_region_name(glyphs, prev_bottom, zone_y_top, used)
        used.add(name)

        box = _make_region_box(zone, disc_ys)
        result[name] = box
        log.info("_region_bounds_stacked: zone %d → %s  %d strips  y=%.0f–%.0f  box=%s",
                 zi, name, len(zone), zone_y_top, zone_y_bottom, box)

    return result


def _parse_single_scan_bounds(xps_path: str) -> tuple[float, float, float, float] | None:
    """
    Return crop bounds for a SINGLE-scan XPS (spine-only, or one femur).

    Unlike _parse_all_strip_bounds which uses hardcoded strip-number ranges
    calibrated for combined (spine+dual-femur) XPS files, this function:
      1. Opens the ZIP and identifies valid scan strips by their image properties
         (non-RGBA, height≥30, width≥300) — no assumed strip numbers.
      2. Reads the fpage XAML and looks up Viewport coords for those strip numbers.
      3. Returns the bounding box of all valid strip Viewports.

    This is robust to GE Lunar single-scan XPS files that may number their
    strips completely differently from the combined report format.
    """
    try:
        with zipfile.ZipFile(xps_path) as z:
            fpage = z.read("Documents/1/Pages/1.fpage").decode("utf-8", errors="replace")
            # Find all valid scan strip numbers from the ZIP contents
            valid_strips: set[int] = set()
            for name in z.namelist():
                if 'Images' not in name or not name.endswith('.PNG'):
                    continue
                try:
                    num = int(name.split('/')[-1].replace('.PNG', ''))
                    raw = z.read(name)
                    img = Image.open(io.BytesIO(raw))
                    if img.mode != 'RGBA' and img.height >= 30 and img.width >= 300:
                        valid_strips.add(num)
                except Exception:
                    pass
    except Exception:
        return None

    if not valid_strips:
        return None

    strip_re = re.compile(
        r'ImageSource="[^"]*Images/(\d+)\.PNG"[^/]*?Viewport="([\d.]+),([\d.]+),([\d.]+),([\d.]+)"'
        r'|'
        r'Viewport="([\d.]+),([\d.]+),([\d.]+),([\d.]+)"[^/]*?ImageSource="[^"]*Images/(\d+)\.PNG"',
        re.IGNORECASE | re.DOTALL,
    )

    boxes: list[tuple[float, float, float, float]] = []
    for m in strip_re.finditer(fpage):
        if m.group(1):
            num = int(m.group(1))
            x, y, w, h = float(m.group(2)), float(m.group(3)), float(m.group(4)), float(m.group(5))
        else:
            num = int(m.group(10))
            x, y, w, h = float(m.group(6)), float(m.group(7)), float(m.group(8)), float(m.group(9))
        if num not in valid_strips or w < 5 or h < 2:
            continue
        boxes.append((x, y, x + w, y + h))

    if not boxes:
        return None

    bx1 = min(b[0] for b in boxes)
    by1 = min(b[1] for b in boxes)
    bx2 = max(b[2] for b in boxes)
    by2 = max(b[3] for b in boxes)

    # Cap bottom at "Image not for diagnosis" disclaimer if present below scan
    all_disclaimer_ys = []
    for m in re.finditer(r'UnicodeString="[^"]*not\s+for\s+diagnosis[^"]*"', fpage, re.IGNORECASE):
        elem_start = fpage.rfind('<Glyphs', 0, m.start())
        if elem_start == -1:
            elem_start = max(0, m.start() - 8000)
        ctx = fpage[elem_start:m.start()]
        oys = re.findall(r'OriginY="([\d.]+)"', ctx)
        if oys:
            all_disclaimer_ys.append(float(oys[-1]))
    local_disclaimers = [y for y in all_disclaimer_ys if by1 < y < by2 + 300]
    if local_disclaimers:
        cap = min(local_disclaimers) - 2
        if cap > by1 + 20:
            by2 = min(by2, cap)

    log.info("_parse_single_scan_bounds: %d valid strips → bounds=(%.1f,%.1f,%.1f,%.1f)",
             len(boxes), bx1, by1, bx2, by2)
    # top_margin: small — ROI boxes start at first strip, no need to reach into header zone.
    # 40 was too large and pulled in the GE Lunar patient-header text above the scan.
    return (max(0, bx1 - 8), max(0, by1 - 8), bx2 - 20, by2 + 2)


def _parse_scan_bounds(xps_path: str) -> tuple[float, float, float, float] | None:
    """
    Return a single crop bound covering all scan strips on page 1.
    Used for single-scan XPS files.  For combined XPS use _parse_all_strip_bounds.

    Tries _parse_single_scan_bounds first (discovers strips from ZIP contents,
    no hardcoded strip-number ranges), then falls back to the clip-path method.
    """
    bounds = _parse_single_scan_bounds(xps_path)
    if bounds:
        return bounds

    # Fallback: clip paths
    try:
        with zipfile.ZipFile(xps_path) as z:
            fpage = z.read("Documents/1/Pages/1.fpage").decode("utf-8", errors="replace")
    except Exception:
        return None

    clip_re = re.compile(
        r'Clip="M\s*([\d.]+),([\d.]+)\s+L\s*[\d.]+,[\d.]+\s+([\d.]+),([\d.]+)'
    )
    scan_clips = []
    for m in clip_re.finditer(fpage):
        x1, y1, x2, y2 = float(m.group(1)), float(m.group(2)), float(m.group(3)), float(m.group(4))
        w, h = x2 - x1, y2 - y1
        if x1 < 300 and w > 30 and h > 20:
            scan_clips.append((x1, y1, x2, y2))

    if not scan_clips:
        return None

    bx1 = min(c[0] for c in scan_clips)
    by1 = min(c[1] for c in scan_clips)
    bx2 = max(c[2] for c in scan_clips)
    by2 = max(c[3] for c in scan_clips)
    return (max(0, bx1 - 8), max(0, by1 - 30), bx2 + 8, by2)


def _is_background_row(row_rgba: np.ndarray) -> bool:
    """
    Return True if every pixel in the row is background.
    Catches both near-white and the GE Lunar pastel-yellow header band.
    """
    r, g, b = row_rgba[:, 0].astype(int), row_rgba[:, 1].astype(int), row_rgba[:, 2].astype(int)
    # Light / pastel background: high R+G, B can be anything ≥ 150 (covers cream/yellow)
    background = (r >= 210) & (g >= 210) & (b >= 150)
    return bool(background.all())


def _auto_trim(img: Image.Image, bg_threshold: int = 230, padding: int = 12) -> Image.Image:
    """
    Trim background rows/cols from top, sides, and bottom.
    Handles both near-white AND the yellow GE Lunar patient-header band.
    """
    rgb = np.array(img.convert('RGB'))
    gray = rgb.mean(axis=2)

    # Top: skip rows that are background (white or yellow)
    r0 = 0
    for i in range(rgb.shape[0]):
        if not _is_background_row(rgb[i]):
            r0 = i
            break

    # Sides: columns with any dark pixel
    dark_cols = np.where(gray.min(axis=0) < bg_threshold)[0]
    if len(dark_cols) == 0:
        return img
    c0, c1 = int(dark_cols[0]), int(dark_cols[-1])

    # Bottom: last non-background row
    r1 = rgb.shape[0] - 1
    for i in range(rgb.shape[0] - 1, -1, -1):
        if not _is_background_row(rgb[i]):
            r1 = i
            break

    left   = max(0,          c0 - padding)
    top    = max(0,          r0 - padding)
    right  = min(img.width,  c1 + padding)
    bottom = min(img.height, r1 + padding)

    # Guard: never produce an invalid box
    if right <= left or bottom <= top:
        return img

    return img.crop((left, top, right, bottom))


def _bounds_to_png(page_png_bytes: bytes, bounds: tuple, dpi: int, label: str = '',
                   trim: bool = True) -> bytes:
    """Crop a rendered page PNG to XPS-unit bounds, return PNG bytes.
    trim=True applies _auto_trim (good for spine); trim=False keeps exact strip extents (femur).
    """
    x1_xps, y1_xps, x2_xps, y2_xps = bounds
    scale = dpi / 96.0
    img = Image.open(io.BytesIO(page_png_bytes))
    w, h = img.size
    box = (
        max(0, int(x1_xps * scale)),
        max(0, int(y1_xps * scale)),
        min(w, int(x2_xps * scale)),
        min(h, int(y2_xps * scale)),
    )
    if box[2] <= box[0] or box[3] <= box[1]:
        log.warning("_bounds_to_png: invalid box %s for %s — using full strip height", box, label)
        box = (box[0], box[1], max(box[0] + 1, box[2]), max(box[1] + 1, min(h, int(y2_xps * scale))))
    cropped = _auto_trim(img.crop(box)) if trim else img.crop(box)
    log.info("crop %s: %dx%d → %dx%d", label, w, h, cropped.width, cropped.height)
    buf = io.BytesIO()
    cropped.save(buf, 'PNG', optimize=True)
    return buf.getvalue()


def _has_scan_content(png_bytes: bytes, min_dark_fraction: float = 0.01) -> bool:
    """Return True if the PNG contains enough dark pixels to be a real scan image.
    Rejects GE Lunar 'No image records match search criteria' placeholders.
    """
    img = Image.open(io.BytesIO(png_bytes)).convert('L')
    arr = np.array(img)
    dark = (arr < 80).sum()
    return dark / arr.size >= min_dark_fraction


def crop_xps_scan_image(page_png_bytes: bytes, xps_path: str, dpi: int = 200) -> bytes:
    """
    Crop a rendered single-scan XPS page to just the scan region.
    Uses ImageBrush Viewport coords; falls back to clip paths.
    """
    bounds = _parse_scan_bounds(xps_path)
    if bounds is None:
        log.warning("crop_xps_scan_image: could not parse bounds — returning full page")
        return page_png_bytes
    return _bounds_to_png(page_png_bytes, bounds, dpi, label=Path(xps_path).name)

# ── Text extraction ────────────────────────────────────────────────────────
def extract_xps_text(xps_path: str) -> list[tuple[float, float, str]]:
    """Return [(x, y, text), ...] sorted by y then x."""
    with zipfile.ZipFile(xps_path) as zf:
        fpage = zf.read('Documents/1/Pages/1.fpage').decode('utf-8')

    pattern = (
        r'OriginX="([\d.]+)"\s+'
        r'OriginY="([\d.]+)"\s+'
        r'(?:[A-Za-z]+="[^"]*"\s+)*?'
        r'Indices="[^"]*"\s+'
        r'UnicodeString="([^"]+)"'
    )
    glyphs = re.findall(pattern, fpage)
    result = [(float(x), float(y), text.strip()) for x, y, text in glyphs if text.strip()]
    return sorted(result, key=lambda t: (t[1], t[0]))


def _group_lines(glyphs: list[tuple[float, float, str]], bucket_px: float = 4.0) -> list[list[tuple[float, str]]]:
    """Group glyphs into lines by bucketing Y coordinates."""
    lines: dict[int, list] = defaultdict(list)
    for x, y, text in glyphs:
        bucket = int(round(y / bucket_px))
        lines[bucket].append((x, text))
    return [sorted(v) for _, v in sorted(lines.items())]


def _line_text(line: list[tuple[float, str]]) -> str:
    return '  '.join(t for _, t in line)


# ── BMD value parsing ──────────────────────────────────────────────────────
# Patterns observed in XPS:
#   Spine: "L12.3  1.210  0.7"  (Z-score embedded before region)
#   Femur: "Neck-0.1  0.809  -1.6"

_SPINE_SITE_RE = re.compile(
    r'(L1-L4|L1-L3|L1-L2|L3-L4|L2-L4|L2-L3|L1|L2|L3|L4)'
    r'([-\d.]+)\s+'        # Z-score (glued to site label)
    r'([\d.]+)\s+'         # BMD
    r'([-\d.]+)'           # T-score
)

_FEMUR_SITE_RE = re.compile(
    r'(Total|Neck|Trochanter|Wards|InterTroch)'
    r'([-\d.]+)\s+'        # Z-score glued
    r'([\d.]+)\s+'         # BMD
    r'([-\d.]+)'           # T-score
)


def _parse_bmd_block(lines: list[list[tuple[float, str]]], site_re) -> dict:
    """Parse one densitometry block from text lines."""
    result = {}
    full_text = '\n'.join(_line_text(l) for l in lines)

    for m in site_re.finditer(full_text):
        site   = m.group(1)
        z      = float(m.group(2))
        bmd    = float(m.group(3))
        t      = float(m.group(4))
        pct_ya = None  # XPS doesn't print %YA directly in this layout

        # %YA is printed as a standalone number earlier in the block
        # We skip it for XPS; MDB provides it as supplementary.
        result[site] = {'bmd': bmd, 'T': t, 'Z': z, 'pYA': pct_ya, 'source': 'XPS'}

    return result


def parse_xps_bmd(xps_path: str) -> dict:
    """
    Parse BMD values from XPS text.

    Returns:
      {
        'spine':        {'L1': {'bmd', 'T', 'Z', 'source'}, ...},
        'left_femur':   {'Neck': {...}, 'Total': {...}},
        'right_femur':  {'Neck': {...}, 'Total': {...}},
        'patient': {'name', 'pid', 'dob_str', 'age_str', 'height_cm', 'weight_kg',
                    'gender', 'scan_date_str', 'scan_time_str', 'physician'},
      }
    """
    glyphs = extract_xps_text(xps_path)
    lines  = _group_lines(glyphs)
    full   = '\n'.join(_line_text(l) for l in lines)

    # ── Patient header ─────────────────────────────────────────────────
    patient = _parse_patient_header(full)

    # ── Split into three scan blocks by "Densitometry Reference:" headers ──
    # Sections appear in order: AP Spine, Left Femur, Right Femur
    section_starts = [m.start() for m in re.finditer(r'Densitometry Reference:', full)]

    def _section(idx: int) -> str:
        start = section_starts[idx] if idx < len(section_starts) else len(full)
        end   = section_starts[idx + 1] if idx + 1 < len(section_starts) else len(full)
        return full[start:end]

    spine_block  = _section(0) if len(section_starts) > 0 else ''
    lfem_block   = _section(1) if len(section_starts) > 1 else ''
    rfem_block   = _section(2) if len(section_starts) > 2 else ''

    spine      = _parse_spine_block(spine_block)
    left_femur = _parse_femur_block(lfem_block)
    right_femur = _parse_femur_block(rfem_block)

    return {
        'patient':     patient,
        'spine':       spine,
        'left_femur':  left_femur,
        'right_femur': right_femur,
    }


def _parse_patient_header(full: str) -> dict:
    result: dict = {}

    m = re.search(r'Patient:\s+(.*?)(?:Facility ID:|$)', full, re.MULTILINE)
    if m:
        raw = m.group(1).strip()
        parts = raw.split(',', 1)
        result['title'] = parts[0].strip() if len(parts) > 1 else ''
        result['name']  = parts[1].strip() if len(parts) > 1 else raw

    m = re.search(r'Birth Date:\s+(\S+)\s+([\d.]+)\s+years', full)
    if m:
        result['dob_str'] = m.group(1)
        result['age_str'] = m.group(2)

    m = re.search(r'Height / Weight:\s+([\d.]+)\s*cm\s+([\d.]+)\s*kg', full)
    if m:
        result['height_cm'] = float(m.group(1))
        result['weight_kg'] = float(m.group(2))

    m = re.search(r'Sex / Ethnic:\s+(\w+)', full)
    if m:
        result['gender'] = m.group(1)

    m = re.search(r'Measured:\s+(\S+)\([\d.]+\)\s+(\S+)', full)
    if m:
        result['scan_date_str'] = m.group(1)
        result['scan_time_str'] = m.group(2)

    m = re.search(r'Referring Physician:\s+(.+?)(?:\n|$)', full)
    if m:
        result['physician'] = m.group(1).strip()

    return result


def _parse_spine_block(text: str) -> dict:
    result = {}
    for m in _SPINE_SITE_RE.finditer(text):
        site = m.group(1)
        result[site] = {
            'bmd': float(m.group(3)),
            'T':   float(m.group(4)),
            'Z':   float(m.group(2)),
            'pYA': None,
            'source': 'XPS',
        }
    return result


def _parse_femur_block(text: str) -> dict:
    result = {}
    for m in _FEMUR_SITE_RE.finditer(text):
        site = m.group(1)
        result[site] = {
            'bmd': float(m.group(3)),
            'T':   float(m.group(4)),
            'Z':   float(m.group(2)),
            'pYA': None,
            'source': 'XPS',
        }
    return result


# ── Image extraction ───────────────────────────────────────────────────────

def _has_scan_images(xps_path: str) -> bool:
    """Quick check: does this XPS contain embedded scan strip images?"""
    try:
        with zipfile.ZipFile(xps_path) as zf:
            names = set(zf.namelist())
            return 'Documents/1/Resources/Images/1.PNG' in names
    except Exception:
        return False


def extract_scan_images(xps_path: str) -> dict[str, Image.Image]:
    """
    Returns {'spine': PIL.Image, 'left_femur': PIL.Image, 'right_femur': PIL.Image}
    for whichever regions are present.

    Uses position-based region detection (_parse_region_bounds_by_position) to
    group strips by scan region — not hardcoded strip-number ranges.  Handles
    both stacked (spine/L-hip/R-hip) and side-by-side (L-hip | R-hip) layouts.
    """
    fpage, strip_boxes = _collect_strip_viewports(xps_path)
    if not strip_boxes:
        log.warning("extract_scan_images: no valid strips in %s", xps_path)
        return {}

    disc_ys = _disclaimer_ys(fpage)
    x_clusters = _x_gap_clusters([b[1] for b in strip_boxes], gap=50.0)

    if len(x_clusters) >= 2:
        region_strip_nums = _strip_nums_sidebyside(strip_boxes, x_clusters, fpage)
    else:
        region_strip_nums = _strip_nums_stacked(strip_boxes, disc_ys, fpage)

    results: dict[str, Image.Image] = {}
    try:
        with zipfile.ZipFile(xps_path) as zf:
            for region, strip_info in region_strip_nums.items():
                # strip_info: list of (strip_num, y_position) sorted by y
                strips: list[Image.Image] = []
                for num, _y in strip_info:
                    path = f'Documents/1/Resources/Images/{num}.PNG'
                    try:
                        img = Image.open(io.BytesIO(zf.read(path))).convert('RGB')
                        strips.append(img)
                    except Exception as e:
                        log.warning("extract_scan_images: could not read strip %d for %s: %s", num, region, e)
                if strips:
                    results[region] = _stitch_and_crop(strips)
                else:
                    log.warning("extract_scan_images: no strips for %s in %s", region, xps_path)
    except Exception as e:
        log.warning("extract_scan_images: ZIP read failed for %s: %s", xps_path, e)

    return results


def _strip_nums_sidebyside(
    strip_boxes: list[tuple[int, float, float, float, float]],
    x_clusters: list[list[float]],
    fpage: str,
) -> dict[str, list[tuple[int, float]]]:
    """Return {region: [(strip_num, y), ...]} for side-by-side layout.
    Region names come from text below each column, not positional order."""
    sorted_clusters = sorted(x_clusters, key=lambda c: min(c))
    boundaries = [float('-inf')] + [
        (max(sorted_clusters[i]) + min(sorted_clusters[i + 1])) / 2
        for i in range(len(sorted_clusters) - 1)
    ] + [float('inf')]

    glyphs = _fpage_glyphs(fpage)
    used: set[str] = set()
    result: dict[str, list[tuple[int, float]]] = {}

    for idx in range(len(sorted_clusters)):
        x_lo, x_hi = boundaries[idx], boundaries[idx + 1]
        col = [b for b in strip_boxes if x_lo < b[1] <= x_hi]
        if not col:
            continue
        col_y_bottom = max(b[4] for b in col)
        name = _zone_region_name(glyphs, col_y_bottom - 10, col_y_bottom + 600, used)
        used.add(name)
        result[name] = _dedup_strips_by_num(col)

    return result


def _strip_nums_stacked(
    strip_boxes: list[tuple[int, float, float, float, float]],
    disc_ys: list[float],
    fpage: str,
) -> dict[str, list[tuple[int, float]]]:
    """Return {region: [(strip_num, y), ...]} for stacked layout.
    Zones are detected from Y-gaps between strips — not disclaimer positions —
    so an extended spine (D11/D12 extra strips) never overflows into the hip zone.
    """
    sorted_boxes = sorted(strip_boxes, key=lambda b: b[2])

    # Cluster strips by Y-gap: a gap > 50 XPS units between consecutive strip
    # bottoms and tops signals a new scan zone.
    zones: list[list[tuple]] = []
    current: list[tuple] = []
    for b in sorted_boxes:
        if current and b[2] - max(c[4] for c in current) > 50:
            zones.append(current)
            current = []
        current.append(b)
    if current:
        zones.append(current)

    glyphs = _fpage_glyphs(fpage)
    used: set[str] = set()
    result: dict[str, list[tuple[int, float]]] = {}

    for zi, zone in enumerate(zones):
        zone_y_top    = min(b[2] for b in zone)
        zone_y_bottom = max(b[4] for b in zone)
        # "Densitometry Reference:" label appears in the gap BEFORE each zone, not within it.
        # Search from the previous zone's bottom (or 0 for zone 0) up to this zone's top.
        prev_bottom = max(b[4] for b in zones[zi - 1]) if zi > 0 else 0.0
        name = _zone_region_name(glyphs, prev_bottom, zone_y_top, used)
        used.add(name)
        result[name] = _dedup_strips_by_num(zone)

    return result


def _stitch_and_crop(strips: list[Image.Image]) -> Image.Image:
    """Stack strips vertically, crop white borders. No colour mapping — original as-is."""
    total_h = sum(s.height for s in strips)
    w = strips[0].width
    full = Image.new('RGB', (w, total_h), (255, 255, 255))
    y = 0
    for s in strips:
        full.paste(s, (0, y))
        y += s.height

    # Crop near-white margins
    arr = np.array(full)
    mask = arr.mean(axis=2) < 245
    rows, cols = np.any(mask, axis=1), np.any(mask, axis=0)
    if rows.any():
        r0, r1 = int(np.where(rows)[0][0]), int(np.where(rows)[0][-1])
        c0, c1 = int(np.where(cols)[0][0]), int(np.where(cols)[0][-1])
        pad = 8
        full = full.crop((
            max(0, c0 - pad), max(0, r0 - pad),
            min(full.width, c1 + pad), min(full.height, r1 + pad),
        ))
    return full




def _extract_scan_strips(xps_path: str) -> Optional[Image.Image]:
    """
    Extract and stitch DEXA scan strips from a single-scan XPS file.
    Strips are identified as: mode=P (palette/grayscale), width≥1000, height≥30.
    RGBA images (logos) and thin bars are automatically excluded.
    Returns None if no valid strips found.
    """
    with zipfile.ZipFile(xps_path) as zf:
        all_imgs = sorted(
            [n for n in zf.namelist() if 'Images' in n and n.endswith('.PNG')],
            key=lambda n: int(n.split('/')[-1].replace('.PNG', ''))
        )
        strips = []
        for img_path in all_imgs:
            try:
                data = zf.read(img_path)
                img = Image.open(io.BytesIO(data))
                # Skip logos (RGBA) and thin bars (height < 30)
                if img.mode == 'RGBA' or img.height < 30 or img.width < 1000:
                    continue
                strips.append(img)
            except Exception as e:
                log.warning("Skipping strip %s: %s", img_path, e)
    if not strips:
        return None
    return _stitch_and_crop(strips)


def extract_osteo_images(
    spine_xps: str = '',
    left_femur_xps: str = '',
    right_femur_xps: str = '',
    left_forearm_xps: str = '',
    right_forearm_xps: str = '',
) -> dict[str, Image.Image]:
    """
    Extract DEXA scan images from per-scan or combined XPS files (osteo workflow).

    If spine, left_femur, and right_femur all point to the same file (GE Lunar
    combined XPS), the strip range assignment (strips 1-9 spine, 10-18 left femur,
    19-29 right femur) is used via extract_scan_images(). Otherwise each XPS is
    treated as a single-scan file and strips are detected dynamically.

    Forearm XPS files (if present) are always treated as single-scan files.

    Returns dict with keys: 'spine', 'left_femur', 'right_femur', 'left_forearm',
    'right_forearm' (only includes keys where an image was successfully extracted).
    """
    paths = {
        'spine':        spine_xps,
        'left_femur':   left_femur_xps,
        'right_femur':  right_femur_xps,
        'left_forearm':  left_forearm_xps,
        'right_forearm': right_forearm_xps,
    }

    # ── Combined XPS: spine, left_femur, right_femur all point to same file ────
    osteo_three_same = (
        spine_xps and left_femur_xps and right_femur_xps
        and spine_xps == left_femur_xps == right_femur_xps
    )
    if osteo_three_same:
        combined_path = spine_xps
        log.info("Combined XPS detected — using strip-range extraction: %s", combined_path)
        result: dict[str, Image.Image] = {}
        try:
            result = extract_scan_images(combined_path)
        except Exception as e:
            log.warning("extract_scan_images failed on combined XPS: %s", e)

        # Handle separate forearm XPS files if present
        for label in ('left_forearm', 'right_forearm'):
            if paths[label]:
                try:
                    img = _extract_scan_strips(paths[label])
                    if img:
                        result[label] = img
                    else:
                        log.warning("No strips found in %s", paths[label])
                except Exception as e:
                    log.warning("Failed to extract %s from %s: %s", label, paths[label], e)
        return result

    # ── Separate per-scan XPS files ──────────────────────────────────────────
    result: dict[str, Image.Image] = {}
    for label, path in paths.items():
        if not path:
            continue
        try:
            img = _extract_scan_strips(path)
            if img:
                result[label] = img
            else:
                log.warning("No strips found in %s", path)
        except Exception as e:
            log.warning("Failed to extract %s from %s: %s", label, path, e)
    return result


def _crop_to_roi_bottom(img: Image.Image, margin_px: int = 10) -> Image.Image:
    """
    Crop hip overlay to just below the lowest substantial black ROI line.

    GE Lunar femur ROI shapes (neck / trochanter trapezoids) are wide black
    strokes spanning 30–200+ pixels per row.  Chart tick marks, axis labels, and
    stray text pixels are narrow (< 10 px).  Requiring ≥ 30 black pixels per row
    keeps only real ROI content and avoids cropping to the bottom of the
    densitometry reference chart drawn below the scan.
    """
    arr = np.array(img.convert('RGB'))
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    black_mask = (r < 60) & (g < 60) & (b < 60)
    black_count = black_mask.sum(axis=1)
    roi_rows = np.where(black_count >= 30)[0]
    if len(roi_rows) == 0:
        # Fallback: any black pixel at all
        roi_rows = np.where(black_mask.any(axis=1))[0]
    if len(roi_rows) == 0:
        return img
    bottom = min(int(roi_rows[-1]) + margin_px, img.height)
    return img.crop((0, 0, img.width, bottom))


def _extend_femur_bounds_and_trim_top(
    page_png: bytes,
    bounds: tuple[float, float, float, float],
    dpi: int,
    label: str,
    extension_xps: float = 80.0,
) -> bytes | None:
    """
    Render a femur overlay crop with the top boundary extended upward by
    `extension_xps` XPS units, then scan downward from the top of that
    extended margin to find the first non-white row (the ROI triangle tip).
    Crops the image there (with a small pad) so the tip is never clipped.

    The extension is applied only to y1; spine and total-body paths are
    not affected — this function is called exclusively for femur overlays.
    """
    x1, y1, x2, y2 = bounds
    extended_bounds = (x1, max(0.0, y1 - extension_xps), x2, y2)
    raw = _bounds_to_png(page_png, extended_bounds, dpi, label=label, trim=False)
    if raw is None:
        return None

    img = Image.open(io.BytesIO(raw))
    arr = np.array(img)
    margin_px = int(extension_xps * dpi / 96)

    # Search only the LOWER 60% of the extended margin for the triangle tip.
    # The triangle tip is at most ~75 XPS units above y1 (= bottom of margin),
    # so it lives in the lower portion.  The upper portion may contain text from
    # the previous zone ("Image not for diagnosis") which must be excluded.
    search_start = int(margin_px * 0.4)  # skip top 40% of margin
    search = arr[search_start:margin_px]
    mask = search.mean(axis=2) < 230
    rows = np.any(mask, axis=1)
    if rows.any():
        tip_row = search_start + int(np.where(rows)[0][0])
        crop_top = max(0, tip_row - 3)
    else:
        crop_top = margin_px  # no tip found — start at strip content

    cropped = img.crop((0, crop_top, img.width, img.height))

    # Bottom trim: remove "Image not for diagnosis" text + horizontal rule that
    # sometimes appears at the bottom of the captured region.
    # Strategy: scan up from bottom — skip trailing white, skip text/rule block,
    # then find where the white gap above the text starts → crop there.
    arr_b = np.array(cropped)
    row_bright = arr_b.mean(axis=(1, 2))
    h = arr_b.shape[0]
    crop_bottom = h
    if h > 20:
        r = h - 1
        # Phase 1: skip trailing white rows
        while r > h // 2 and row_bright[r] > 240:
            r -= 1
        # Phase 2: skip non-white block (text + rule line)
        while r > h // 2 and row_bright[r] <= 240:
            r -= 1
        # Phase 3: if we're now in a white gap above the text, scan up to scan content
        if row_bright[r] > 240 and r > h // 2:
            while r > 0 and row_bright[r] > 240:
                r -= 1
            crop_bottom = min(h, r + 4)  # last scan-content row + small pad

    if crop_bottom < h:
        cropped = cropped.crop((0, 0, cropped.width, crop_bottom))

    buf = io.BytesIO()
    cropped.save(buf, 'PNG', optimize=True)
    return buf.getvalue()


def render_osteo_overlay_pages(
    spine_xps: str = None,
    left_femur_xps: str = None,
    right_femur_xps: str = None,
    left_forearm_xps: str = None,
    right_forearm_xps: str = None,
    dpi: int = 200,
) -> dict[str, bytes]:
    """
    Render XPS pages to PNG using mutool, preserving the ROI overlay lines
    (the L1-L4 boxes, femur neck lines, forearm bounds, etc.) that are XAML vector paths and
    cannot be captured from raw strip PNGs.

    Returns dict with PNG bytes keyed by slot name:
      'spine_overlay'            — page(s) from the spine XPS
      'left_femur_overlay'       — page(s) from the left femur XPS
      'right_femur_overlay'      — page(s) from the right femur XPS
      'left_forearm_overlay'     — page(s) from the left forearm XPS
      'right_forearm_overlay'    — page(s) from the right forearm XPS

    For combined XPS (all labels point to same file) the pages are split accordingly.

    Missing keys mean rendering failed or no XPS was provided.
    """
    all_three_same = (
        spine_xps and left_femur_xps and right_femur_xps
        and spine_xps == left_femur_xps == right_femur_xps
    )
    dual_femur_only = (
        not spine_xps
        and left_femur_xps and right_femur_xps
        and left_femur_xps == right_femur_xps
    )

    out: dict[str, bytes] = {}

    _FEMUR_SLOTS = ('left_femur_overlay', 'right_femur_overlay')
    _FEMUR_REGIONS = ('left_femur', 'right_femur')

    def _render_region(page_png: bytes, bounds: tuple, key: str) -> bytes | None:
        """Crop page_png to exact strip bounds — no auto_trim for any region."""
        is_femur = key in _FEMUR_SLOTS
        if is_femur:
            raw = _extend_femur_bounds_and_trim_top(page_png, bounds, dpi, label=key)
        else:
            raw = _bounds_to_png(page_png, bounds, dpi, label=key, trim=False)
        if not raw or not _has_scan_content(raw):
            log.info("render_osteo_overlay_pages: no scan content in %s — skipping", key)
            return None
        return raw

    if dual_femur_only:
        pages = render_xps_pages(left_femur_xps, dpi=dpi)
        if pages:
            region_bounds = _parse_region_bounds_by_position(left_femur_xps)
            for region, key in [('left_femur', 'left_femur_overlay'), ('right_femur', 'right_femur_overlay')]:
                if region in region_bounds:
                    result = _render_region(pages[0], region_bounds[region], key)
                    if result:
                        out[key] = result
                else:
                    log.warning("render_osteo_overlay_pages: no bounds for %s in dual-femur XPS", region)

    elif all_three_same:
        pages = render_xps_pages(spine_xps, dpi=dpi)
        if pages:
            page_png = pages[0]
            region_bounds = _parse_region_bounds_by_position(spine_xps)
            for region, key in [
                ('spine',       'spine_overlay'),
                ('left_femur',  'left_femur_overlay'),
                ('right_femur', 'right_femur_overlay'),
            ]:
                if region in region_bounds:
                    result = _render_region(page_png, region_bounds[region], key)
                    if result:
                        out[key] = result
                else:
                    log.warning("render_osteo_overlay_pages: no strip bounds for %s", region)

    # Separate XPS files — each has its own single page. Also catches a forearm
    # file saved apart from a combined spine+femur XPS (the dual_femur_only/
    # all_three_same branches above only cover spine+femur, deliberately don't
    # `return` so this loop still runs for whichever labels aren't done yet).
    _slot_to_region = {
        'spine_overlay':            'spine',
        'left_femur_overlay':       'left_femur',
        'right_femur_overlay':      'right_femur',
        'left_forearm_overlay':     'left_forearm',
        'right_forearm_overlay':    'right_forearm',
    }
    for label, path in [
        ('spine_overlay',           spine_xps),
        ('left_femur_overlay',      left_femur_xps),
        ('right_femur_overlay',     right_femur_xps),
        ('left_forearm_overlay',    left_forearm_xps),
        ('right_forearm_overlay',   right_forearm_xps),
    ]:
        if label in out:
            continue
        if not path:
            continue
        pages = render_xps_pages(path, dpi=dpi)
        if not pages:
            continue
        region_bounds = _parse_region_bounds_by_position(path)
        target_region = _slot_to_region[label]
        if target_region not in region_bounds:
            log.warning("render_osteo_overlay_pages: no bounds for %s in %s", target_region, path)
            continue
        result = _render_region(pages[0], region_bounds[target_region], label)
        if result:
            out[label] = result

    return out


# ── XPS type detection ────────────────────────────────────────────────────
_TB_COMPOSITION_RE = re.compile(
    r'%\s*Fat|Android\s*%|Gynoid|Lean\s+Mass', re.IGNORECASE
)
_TB_BONE_REGION_RE = re.compile(
    r'(?:Pelvis|Trunk|Ribs)\s+[\d.]+\s+[\d.]+', re.IGNORECASE
)
_TB_BONE_TITLE_RE = re.compile(
    r'Total\s+Body\s+Bone\s+Density', re.IGNORECASE
)


def detect_xps_type(xps_path: str) -> str:
    """
    Sniff XPS text to determine scan type without full parsing.

    Returns one of:
      'spine_femur'           – AP Spine + Dual Femur densitometry report
      'totalbody_bone'        – total-body bone-density by region (one Densitometry Reference: Total)
      'totalbody_composition' – fat/lean/BMC tissue quantitation
      'totalbody_narrative'   – patient letter / narrative (no structured data)
      'unknown'               – unrecognised or unreadable
    """
    try:
        glyphs = extract_xps_text(xps_path)
    except Exception as e:
        log.warning("detect_xps_type: cannot read %s — %s", xps_path, e)
        return 'unknown'

    full = ' '.join(t for _, _, t in glyphs)

    # Check total-body bone region markers FIRST — Pelvis/Trunk/Ribs followed by
    # numbers only appear in total-body bone density reports, never in spine/femur
    # osteo reports.  Must come before the densitometry-count check because a
    # multi-region TB bone XPS (Head, Arms, Trunk, Pelvis, Ribs, Spine, Total …)
    # has many "Densitometry Reference:" sections and would otherwise be mis-
    # classified as 'spine_femur'.
    # "Total Body Bone Density" title is present on every TB bone page —
    # catches single-region exports (e.g. Head-only) that lack Pelvis/Trunk/Ribs.
    if _TB_BONE_REGION_RE.search(full) or _TB_BONE_TITLE_RE.search(full):
        return 'totalbody_bone'

    # Spine+femur: has at least 2 "Densitometry Reference:" sections
    # (spine + left femur + right femur = 3). Total-body bone has exactly 1
    # ("Densitometry Reference: Total") — but the multi-region case is caught above.
    densito_count = len(re.findall(r'Densitometry Reference:', full))
    if densito_count >= 2:
        return 'spine_femur'
    if densito_count == 1:
        # Spine-only XPS also has exactly 1 Densitometry Reference section.
        # Distinguish by presence of vertebra or AP Spine labels.
        if re.search(r'AP\s+Spine|Lumbar\s+Spine|L1[-–]L4|L[1-4]\b', full, re.IGNORECASE):
            return 'spine_femur'
        return 'totalbody_bone'

    if _TB_COMPOSITION_RE.search(full):
        return 'totalbody_composition'

    if _TB_BONE_REGION_RE.search(full):
        return 'totalbody_bone'

    return 'totalbody_narrative'


# ── Data reconciliation ────────────────────────────────────────────────────
def reconcile(xps_data: dict, mdb_session: dict) -> dict:
    """
    Merge XPS (authoritative BMD/T/Z) with MDB (authoritative BMC/Area/Ward's/Trochanter).
    Returns a unified dict ready for render_pdf.
    """
    def _merge_site(xps_site: Optional[dict], mdb_site: Optional[dict]) -> Optional[dict]:
        if xps_site is None and mdb_site is None:
            return None
        merged = {}
        if mdb_site:
            merged.update(mdb_site)
        if xps_site:
            # XPS wins for BMD, T, Z
            merged['bmd']    = xps_site['bmd']
            merged['T']      = xps_site['T']
            merged['Z']      = xps_site['Z']
            merged['source'] = 'XPS'
        return merged

    def _merge_region(xps_region: dict, mdb_region: dict, sites: list[str]) -> dict:
        result = {}
        all_sites = set(list(xps_region.keys()) + list(mdb_region.keys()) + sites)
        for site in all_sites:
            merged = _merge_site(xps_region.get(site), mdb_region.get(site))
            if merged:
                result[site] = merged
        return result

    spine      = _merge_region(xps_data.get('spine', {}),       mdb_session.get('spine', {}),       ['L1','L2','L3','L4','L1-L4'])
    left_femur = _merge_region(xps_data.get('left_femur', {}),  mdb_session.get('left_femur', {}),  ['Neck','Wards','Trochanter','Total'])
    right_femur = _merge_region(xps_data.get('right_femur', {}), mdb_session.get('right_femur', {}), ['Neck','Total'])

    return {
        'spine':       spine,
        'left_femur':  left_femur,
        'right_femur': right_femur,
    }
