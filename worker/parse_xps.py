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

    GE Lunar strip assignments (verified):
      Strips  1– 9  → 'spine'
      Strips 10–18  → 'left_femur'
      Strips 19–29  → 'right_femur'

    Returns dict with keys from the above set, only for regions that have strips.
    Values are (x1, y1, x2, y2) in XPS units with a small margin.
    """
    _STRIP_REGIONS = {
        'spine':       range(1, 10),
        'left_femur':  range(10, 19),
        'right_femur': range(19, 30),
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
    # Each scan region has its own disclaimer; they must be applied per-region.
    all_disclaimer_ys = []
    for m in re.finditer(r'not\s+for\s+diagnosis', fpage, re.IGNORECASE):
        ctx = fpage[max(0, m.start() - 800) : m.start() + 200]
        for oy in re.findall(r'OriginY="([\d.]+)"', ctx):
            all_disclaimer_ys.append(float(oy))

    result = {}
    left_margin  =  8   # expand left slightly
    right_margin = 20   # trim right (scale bar lives here)
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
        result[region] = (max(0, bx1 - left_margin), max(0, by1 - 18), bx2 - right_margin, by2 + 2)
        log.info("_parse_all_strip_bounds: %s → %d strips, bounds=%s cap_y=%s",
                 region, len(boxes), result[region], local_disclaimers or None)

    return result


def _parse_scan_bounds(xps_path: str) -> tuple[float, float, float, float] | None:
    """
    Return a single crop bound covering all scan strips on page 1.
    Used for single-scan XPS files.  For combined XPS use _parse_all_strip_bounds.
    """
    all_bounds = _parse_all_strip_bounds(xps_path)
    if all_bounds:
        # Union of all regions
        all_boxes = list(all_bounds.values())
        bx1 = min(b[0] for b in all_boxes)
        by1 = min(b[1] for b in all_boxes)
        bx2 = max(b[2] for b in all_boxes)
        by2 = max(b[3] for b in all_boxes)
        return (bx1, by1, bx2, by2)

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
    Trim background rows/cols from top and sides.
    Handles both near-white AND the yellow GE Lunar patient-header band.
    Bottom is left as-is (already hard-cut by XPS clip by2).
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

    # Bottom: last non-background row (removes blank below scan strips)
    r1 = rgb.shape[0] - 1
    for i in range(rgb.shape[0] - 1, -1, -1):
        if not _is_background_row(rgb[i]):
            r1 = i
            break

    box = (
        max(0,          c0 - padding),
        max(0,          r0 - padding),
        min(img.width,  c1 + padding),
        min(img.height, r1 + padding),
    )
    return img.crop(box)


def _bounds_to_png(page_png_bytes: bytes, bounds: tuple, dpi: int, label: str = '') -> bytes:
    """Crop a rendered page PNG to XPS-unit bounds, auto-trim, return PNG bytes."""
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
        log.warning("_bounds_to_png: invalid box %s for %s — skipping cap, using full strip height", box, label)
        box = (box[0], box[1], max(box[0] + 1, box[2]), max(box[1] + 1, min(h, int(y2_xps * scale))))
    cropped = _auto_trim(img.crop(box))
    log.info("crop %s: %dx%d → %dx%d", label, w, h, cropped.width, cropped.height)
    buf = io.BytesIO()
    cropped.save(buf, 'PNG', optimize=True)
    return buf.getvalue()


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
_STRIP_ASSIGNMENTS = {
    'spine':       range(1, 10),    # strips 1-9
    'left_femur':  range(10, 19),   # strips 10-18
    'right_femur': range(19, 30),   # strips 19-29
}


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
    Images are stitched from PNG strips and false-coloured.

    GE Lunar strip layout (verified on SDRC hardware):
      Strips 1–9   → AP Spine
      Strips 10–18 → Left Femur  (strip 10 is a thin separator — skipped)
      Strips 19–29 → Right Femur (strip 19 is a thin separator, 29 is RGBA logo — both skipped)

    Strips are skipped if they are:
      • RGBA mode (logos / overlays)
      • Height < 20 px (separator lines)
    """
    results = {}
    with zipfile.ZipFile(xps_path) as zf:
        available = {n for n in zf.namelist() if n.startswith('Documents/1/Resources/Images/')}
        for label, nums in _STRIP_ASSIGNMENTS.items():
            strips = []
            for n in nums:
                path = f'Documents/1/Resources/Images/{n}.PNG'
                if path not in available:
                    break
                try:
                    data = zf.read(path)
                    img = Image.open(io.BytesIO(data))
                    # Skip RGBA logos and thin separator lines
                    if img.mode == 'RGBA' or img.height < 20:
                        log.debug("Skipping strip %d for %s (%s %dx%d)", n, label, img.mode, img.width, img.height)
                        continue
                    strips.append(img.convert('RGB'))
                except Exception as e:
                    log.warning("Skipping strip %d for %s: %s", n, label, e)
                    break
            if strips:
                results[label] = _stitch_and_crop(strips)
            else:
                log.warning("No usable strips found for %s in %s", label, xps_path)
    return results


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
    spine_xps: str,
    left_femur_xps: str,
    right_femur_xps: str,
) -> dict[str, Image.Image]:
    """
    Extract DEXA scan images from per-scan or combined XPS files (osteo workflow).

    If all three paths point to the same file (GE Lunar combined XPS), the strip
    range assignment (strips 1-9 spine, 10-18 left femur, 19-29 right femur) is
    used via extract_scan_images().  Otherwise each XPS is treated as a
    single-scan file and strips are detected dynamically.

    Returns dict with keys: 'spine', 'left_femur', 'right_femur'
    (only includes keys where an image was successfully extracted).
    """
    paths = {
        'spine':       spine_xps,
        'left_femur':  left_femur_xps,
        'right_femur': right_femur_xps,
    }

    # ── Combined XPS: ALL three labels present and point to the same file ──────
    # (not just 1 unique path — that also matches a spine-only per-scan case)
    all_three_same = (
        spine_xps and left_femur_xps and right_femur_xps
        and spine_xps == left_femur_xps == right_femur_xps
    )
    if all_three_same:
        combined_path = spine_xps
        log.info("Combined XPS detected — using strip-range extraction: %s", combined_path)
        try:
            return extract_scan_images(combined_path)
        except Exception as e:
            log.warning("extract_scan_images failed on combined XPS: %s", e)
            return {}

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


def render_osteo_overlay_pages(
    spine_xps: str,
    left_femur_xps: str,
    right_femur_xps: str,
    dpi: int = 200,
) -> dict[str, bytes]:
    """
    Render XPS pages to PNG using mutool, preserving the ROI overlay lines
    (the L1-L4 boxes, femur neck lines, etc.) that are XAML vector paths and
    cannot be captured from raw strip PNGs.

    Returns dict with PNG bytes keyed by slot name:
      'spine_overlay'       — page(s) from the spine XPS
      'left_femur_overlay'  — page(s) from the left femur XPS
      'right_femur_overlay' — page(s) from the right femur XPS

    For combined XPS (all three labels point to same file) the pages are split:
      page 1 → spine, page 2 → left femur, page 3 → right femur.

    Missing keys mean rendering failed or no XPS was provided.
    """
    all_three_same = (
        spine_xps and left_femur_xps and right_femur_xps
        and spine_xps == left_femur_xps == right_femur_xps
    )

    out: dict[str, bytes] = {}

    if all_three_same:
        # Combined XPS: single page with all three scans stacked vertically.
        # Render once, then crop each region using per-strip Viewport bounds.
        pages = render_xps_pages(spine_xps, dpi=dpi)
        if not pages:
            return out
        page_png = pages[0]
        region_bounds = _parse_all_strip_bounds(spine_xps)
        for region, key in [
            ('spine',       'spine_overlay'),
            ('left_femur',  'left_femur_overlay'),
            ('right_femur', 'right_femur_overlay'),
        ]:
            if region in region_bounds:
                out[key] = _bounds_to_png(page_png, region_bounds[region], dpi, label=key)
            else:
                log.warning("render_osteo_overlay_pages: no strip bounds for %s", region)

        # Normalise both femur PNGs to the same pixel dimensions so they render
        # identically in the report. Resize to the larger of the two, preserving
        # each image's correctly-cropped content.
        if 'left_femur_overlay' in out and 'right_femur_overlay' in out:
            lf_img = Image.open(io.BytesIO(out['left_femur_overlay']))
            rf_img = Image.open(io.BytesIO(out['right_femur_overlay']))
            tw = max(lf_img.width,  rf_img.width)
            th = max(lf_img.height, rf_img.height)
            for slot, img in [('left_femur_overlay', lf_img), ('right_femur_overlay', rf_img)]:
                if img.width != tw or img.height != th:
                    img = img.resize((tw, th), Image.LANCZOS)
                buf = io.BytesIO()
                img.save(buf, 'PNG', optimize=True)
                out[slot] = buf.getvalue()
            log.info("render_osteo_overlay_pages: normalised femur PNGs to %dx%d", tw, th)

        return out

    # Separate XPS files — each has its own single page
    for label, path in [
        ('spine_overlay',       spine_xps),
        ('left_femur_overlay',  left_femur_xps),
        ('right_femur_overlay', right_femur_xps),
    ]:
        if not path:
            continue
        pages = render_xps_pages(path, dpi=dpi)
        if pages:
            out[label] = crop_xps_scan_image(pages[0], path, dpi=dpi)

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
