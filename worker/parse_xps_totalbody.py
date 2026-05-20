"""
XPS parsers for GE Lunar DPX Total Body reports.

Two sub-types:
  totalbody_bone        – Full_body.xps   (regional bone density)
  totalbody_composition – Full_body-1.xps (clinical tissue quantitation)
                          Full_body-2.xps  (consumer narrative — same data, cleaner labels)
"""
import io
import re
import zipfile
import logging

import numpy as np
from PIL import Image

from parse_xps import extract_xps_text, _group_lines, _line_text, _parse_patient_header

log = logging.getLogger(__name__)

BONE_REGIONS_ORDER = ['Head', 'Arms', 'Legs', 'Trunk', 'Ribs', 'Pelvis', 'Spine', 'Total']


# ── Image colorization ────────────────────────────────────────────────────────

def colorize_dexa_silhouette(img: Image.Image, mode: str = 'fat_lean') -> Image.Image:
    """
    Apply false-color to a grayscale GE Lunar DEXA body scan.

    GE Lunar total-body images have white background (intensity >= 238).
    Within the body, pixel intensity reflects X-ray attenuation:
      low  attenuation (intensity 30-130)  = fat tissue      → PINK  #E91E8C
      mid  attenuation (intensity 130-200) = lean muscle     → CYAN  #00BCD4
      high attenuation (intensity 200-237) = bone / dense    → light gray

    mode='fat_lean': full fat/lean/bone coloring (for composition pages)
    mode='fat_only': fat=PINK, everything else light gray (for fat-emphasis pages)
    mode='lean_only': lean=CYAN, everything else light gray
    mode='bone': keep grayscale body, white background (for bone health page)
    """
    arr = np.array(img.convert('L'), dtype=np.float32)
    h, w = arr.shape
    out = np.ones((h, w, 3), dtype=np.uint8) * 255  # white background

    BG = arr >= 238  # white background mask

    PINK_c = np.array([233, 30, 140], dtype=np.float32)
    CYAN_c = np.array([0, 188, 212], dtype=np.float32)
    BONE_c = np.array([210, 210, 210], dtype=np.float32)

    if mode == 'bone':
        body_m = ~BG
        v = arr[body_m]
        out[body_m] = np.stack([v, v, v], axis=-1).astype(np.uint8)
        return Image.fromarray(out, 'RGB')

    fat_m  = (~BG) & (arr < 130)
    lean_m = (~BG) & (arr >= 130) & (arr < 200)
    bone_m = (~BG) & (arr >= 200)

    if mode == 'fat_lean':
        out[bone_m] = BONE_c.astype(np.uint8)
        out[fat_m]  = PINK_c.astype(np.uint8)
        out[lean_m] = CYAN_c.astype(np.uint8)
        # Smooth gradient blend at fat/lean boundary
        blend_m = (~BG) & (arr >= 115) & (arr < 145)
        if blend_m.any():
            t = np.clip((arr[blend_m] - 115) / 30.0, 0, 1)
            out[blend_m] = ((1 - t[:, None]) * PINK_c + t[:, None] * CYAN_c).astype(np.uint8)
    elif mode == 'fat_only':
        gray = np.array([220, 220, 220], dtype=np.float32)
        body_m = ~BG
        out[body_m] = gray.astype(np.uint8)
        out[fat_m]  = PINK_c.astype(np.uint8)
    elif mode == 'lean_only':
        gray = np.array([220, 220, 220], dtype=np.float32)
        body_m = ~BG
        out[body_m] = gray.astype(np.uint8)
        out[lean_m] = CYAN_c.astype(np.uint8)
    elif mode == 'fat_gradient':
        # Continuous intensity → fat-scale gradient (background ≥238 stays white)
        # Intensity bands and their anchor colors:
        #   0– 90  → RED   #C62828
        #  90–120  → PINK  #E91E8C
        # 120–150  → PURPLE #7B1FA2
        # 150–185  → BLUE  #1565C0
        # 185–237  → LGRAY #D0D0D0
        # 6 stop values, 6 anchor colors — one color per boundary point
        stops = np.array([0, 90, 120, 150, 185, 237], dtype=np.float32)
        colors = np.array([
            [198, 40,  40],   # RED    #C62828  (intensity 0)
            [233, 30, 140],   # PINK   #E91E8C  (intensity 90)
            [123, 31, 162],   # PURPLE #7B1FA2  (intensity 120)
            [ 21, 101, 192],  # BLUE   #1565C0  (intensity 150)
            [208, 208, 208],  # LGRAY  #D0D0D0  (intensity 185)
            [208, 208, 208],  # LGRAY  #D0D0D0  (intensity 237 — stays gray)
        ], dtype=np.float32)

        body_m = ~BG
        v = arr[body_m]
        # For each pixel find which segment it falls in and interpolate
        rgb = np.zeros((v.shape[0], 3), dtype=np.float32)
        for seg in range(len(stops) - 1):
            lo, hi = stops[seg], stops[seg + 1]
            mask = (v >= lo) & (v < hi)
            if mask.any():
                t = np.clip((v[mask] - lo) / (hi - lo), 0.0, 1.0)
                c0 = colors[seg]
                c1 = colors[seg + 1]
                rgb[mask] = (1 - t[:, None]) * c0 + t[:, None] * c1
        # Pixels at exactly upper stop get LGRAY
        at_top = v >= stops[-1]
        if at_top.any():
            rgb[at_top] = colors[-1]
        out[body_m] = np.clip(rgb, 0, 255).astype(np.uint8)

    return Image.fromarray(out, 'RGB')

# ── Bone density (Full_body.xps) ──────────────────────────────────────────────

# Handles both dash-separated (Head- 1.234 -) and whitespace-separated (Head 1.234) formats
_REGION_RE    = re.compile(r'(Head|Arms|Legs|Trunk|Ribs|Pelvis|Spine)(?:\s*-\s*|\s+)([\d.]+)(?:\s*-|\b)')
_TOTAL_BMD_RE = re.compile(r'Total([-+]?[\d.]+)\s+([\d.]+)\s+([-+]?[\d.]+)')
# Total<Z>  <BMD>  <T>  (Z is glued to "Total" like "Total0.2")


def parse_totalbody_bone(xps_path: str) -> dict:
    """
    Parse Full_body.xps — Total Body Bone Density by region.

    Returns:
      {
        'patient': {...},
        'regions': {
          'Head':  {'bmd': 2.395},
          ...
          'Total': {'bmd': 1.124, 'T': 0.0, 'Z': 0.2},
        }
      }
    """
    glyphs  = extract_xps_text(xps_path)
    lines   = _group_lines(glyphs)
    full    = '\n'.join(_line_text(l) for l in lines)
    patient = _parse_patient_header(full)

    regions: dict = {}
    for m in _REGION_RE.finditer(full):
        try:
            regions[m.group(1)] = {'bmd': float(m.group(2))}
        except ValueError:
            pass

    m = _TOTAL_BMD_RE.search(full)
    if m:
        try:
            regions['Total'] = {
                'Z':   float(m.group(1)),
                'bmd': float(m.group(2)),
                'T':   float(m.group(3)),
            }
        except ValueError:
            pass

    log.info("parse_totalbody_bone: %d regions from %s", len(regions), xps_path)
    return {'patient': patient, 'regions': regions}


# ── Composition (Full_body-1.xps / Full_body-2.xps) ──────────────────────────

# Fat distribution row (Full_body-1.xps style):
# "21-08-2025  43.5  45.6  51.2  0.89  45.4"
_FAT_DIST_RE = re.compile(
    r'\d{2}-\d{2}-\d{4}\s+'
    r'([\d.]+)\s+'   # age
    r'([\d.]+)\s+'   # android %fat
    r'([\d.]+)\s+'   # gynoid %fat
    r'([\d.]+)\s+'   # A/G ratio
    r'([\d.]+)'      # total body %fat
)

# Main data row (Full_body-1.xps style) — numbers concatenated:
# "21-08-202527,9472,047  43.5  45.4  94  63.6  ..."
_MAIN_ROW_RE = re.compile(
    r'\d{2}-\d{2}-\d{4}'
    r'(\d+,\d{3})'      # fat_g  (e.g. "27,947")
    r'(\d+,\d{3})'      # bmc_g  (e.g.  "2,047" glued)
    r'\s+([\d.]+)'      # age
    r'\s+([\d.]+)'      # fat_pct
    r'\s+(\d+)'         # centile
    r'\s+([\d.]+)'      # total_kg
    r'.*?'
    r'(\d+,\d{3})'      # lean_g  (e.g. "33,606")
    r'(\d+,\d{3})'      # fat_free_g (e.g. "35,653", glued to lean_g)
, re.DOTALL)

_BMI_RE       = re.compile(r'BMI\s*=\s*([\d.,]+)')

# Full_body-2.xps (consumer narrative) — clean labeled fields:
_TW_RE   = re.compile(r'Total Weight:\s*([\d.,]+)\s*kg', re.IGNORECASE)
_LEAN_RE = re.compile(r'Lean Weight:\s*([\d.,]+)\s*g',  re.IGNORECASE)
_FAT_RE  = re.compile(r'Fat Weight:\s*([\d.,]+)\s*g',   re.IGNORECASE)
_FPCT_RE = re.compile(r'Tissue %Fat:\s*([\d.,]+)%',     re.IGNORECASE)


def _eu_float(s: str) -> float:
    """
    Parse a number that may use European formatting:
      - Period as thousands separator  (33.606 → 33606)
      - Comma as decimal separator     (63,6   → 63.6)
    Heuristic: if the string has a period and ≥3 digits follow it → thousands sep.
    """
    s = s.strip().replace(' ', '')
    if re.search(r'\.\d{3}$', s):   # e.g. 33.606 — period is thousands sep
        return float(s.replace('.', ''))
    return float(s.replace(',', '.'))


def _comma_int(s: str) -> int:
    """'27,947' → 27947"""
    return int(s.replace(',', ''))


def parse_totalbody_composition(xps_path: str) -> dict:
    """
    Parse Full_body-1.xps or Full_body-2.xps — body composition.

    Returns:
      {
        'patient':          {...},
        'fat_g':            27947,
        'lean_g':           33606,
        'bmc_g':            2047,
        'fat_free_g':       35653,
        'total_kg':         63.6,
        'fat_pct':          45.4,
        'android_fat_pct':  45.6,
        'gynoid_fat_pct':   51.2,
        'ag_ratio':         0.89,
        'centile':          94,
        'bmi':              26.0,
      }
    """
    glyphs  = extract_xps_text(xps_path)
    lines   = _group_lines(glyphs)
    full    = '\n'.join(_line_text(l) for l in lines)
    patient = _parse_patient_header(full)

    result: dict = {'patient': patient}

    # ── Fat distribution (android / gynoid / A/G) ──────────────────
    m = _FAT_DIST_RE.search(full)
    if m:
        result['android_fat_pct'] = float(m.group(2))
        result['gynoid_fat_pct']  = float(m.group(3))
        result['ag_ratio']        = float(m.group(4))
        result['fat_pct']         = float(m.group(5))

    # ── BMI ────────────────────────────────────────────────────────
    m = _BMI_RE.search(full)
    if m:
        try:
            result['bmi'] = _eu_float(m.group(1))
        except ValueError:
            pass

    # ── Main data row (Full_body-1 style) ──────────────────────────
    m = _MAIN_ROW_RE.search(full)
    if m:
        result['fat_g']     = _comma_int(m.group(1))
        result['bmc_g']     = _comma_int(m.group(2))
        result.setdefault('fat_pct', float(m.group(4)))
        result['centile']   = int(m.group(5))
        raw_total = m.group(6)
        try:
            result['total_kg'] = float(raw_total)
        except ValueError:
            # Two numbers merged without space (e.g. "112.749.3" = "112.7" + "49.3")
            # Extract the first valid float by stopping before the second decimal group
            mm = re.match(r'(\d+\.\d+?)(?=\d*\.)', raw_total) or re.match(r'(\d+(?:\.\d+)?)', raw_total)
            if mm:
                result['total_kg'] = float(mm.group(1))
        result['lean_g']    = _comma_int(m.group(7))
        result['fat_free_g']= _comma_int(m.group(8))

    # ── Consumer narrative labels (Full_body-2 style) ─────────────
    # Use as fallback / fill-in for any missing values
    def _try(pattern, key, transform=_eu_float):
        if key not in result:
            mm = pattern.search(full)
            if mm:
                try:
                    result[key] = transform(mm.group(1))
                except ValueError:
                    pass

    _try(_TW_RE,   'total_kg')
    _try(_LEAN_RE, 'lean_g',   lambda s: int(_eu_float(s)))
    _try(_FAT_RE,  'fat_g',    lambda s: int(_eu_float(s)))
    _try(_FPCT_RE, 'fat_pct')

    log.info("parse_totalbody_composition: fat_pct=%s ag=%s bmi=%s",
             result.get('fat_pct'), result.get('ag_ratio'), result.get('bmi'))
    return result


# ── Total-body image extraction ───────────────────────────────────────────────

_IMGBRUSH_RE = re.compile(
    r'<Path\s[^>]*Data="([^"]+)"[^>]*>.*?<ImageBrush\s+ImageSource="([^"]+)"',
    re.DOTALL,
)
_RECT_RE = re.compile(
    r'M\s*([\d.]+),([\d.]+)\s+L\s*([\d.]+),([\d.]+)\s+([\d.]+),([\d.]+)\s+([\d.]+),([\d.]+)'
)


def _stitch_raw(strips: list) -> Image.Image:
    """Stitch strips top-to-bottom, convert to RGB, crop white margins."""
    total_h = sum(s.height for s in strips)
    w = strips[0].width
    canvas = Image.new('RGB', (w, total_h), (255, 255, 255))
    y = 0
    for s in strips:
        canvas.paste(s.convert('RGB'), (0, y))
        y += s.height

    arr = np.array(canvas)
    mask = ~((arr[:, :, 0] > 238) & (arr[:, :, 1] > 238) & (arr[:, :, 2] > 238))
    rows = np.any(mask, axis=1)
    cols = np.any(mask, axis=0)
    if rows.any() and cols.any():
        r0, r1 = int(np.where(rows)[0][0]), int(np.where(rows)[0][-1])
        c0, c1 = int(np.where(cols)[0][0]), int(np.where(cols)[0][-1])
        pad = 8
        canvas = canvas.crop((
            max(0, c0 - pad), max(0, r0 - pad),
            min(canvas.width, c1 + pad + 1), min(canvas.height, r1 + pad + 1),
        ))
    return canvas


def _body_column_bounds(bone_xps: str) -> 'tuple | None':
    """
    Return XPS-unit bounding box (x1, y1, x2, y2) for the body silhouette
    (left) column in Full_body.xps.

    Full_body.xps has two columns of ImageBrush strips side-by-side:
      left  → soft-tissue / bone silhouette body scan
      right → BMD chart with numbers

    We read the Path Data rectangles to find which strips belong to the left
    column (lowest X origin) and return their combined bounding box.
    """
    try:
        with zipfile.ZipFile(bone_xps) as zf:
            fpage = zf.read('Documents/1/Pages/1.fpage').decode('utf-8')

        entries = []
        for data, src in _IMGBRUSH_RE.findall(fpage):
            m = _RECT_RE.match(data.strip())
            if not m:
                continue
            pts = [float(x) for x in m.groups()]
            # Rectangle path: M x1,y1 L x2,y1 x2,y2 x1,y2
            x1, y1 = pts[0], pts[1]
            x2, y2 = pts[4], pts[5]
            entries.append((round(x1, 0), x1, y1, x2, y2))

        if not entries:
            return None

        x_groups = sorted({e[0] for e in entries})
        if len(x_groups) < 2:
            return None   # cannot distinguish columns

        left_x = x_groups[0]
        left_boxes = [(x1, y1, x2, y2) for rx, x1, y1, x2, y2 in entries if rx == left_x]
        if not left_boxes:
            return None

        col_x1 = min(b[0] for b in left_boxes)
        col_y1 = min(b[1] for b in left_boxes)
        col_x2 = max(b[2] for b in left_boxes)
        col_y2 = max(b[3] for b in left_boxes)

        # No margin — let render_totalbody_bone_overlay do pixel-aware trimming
        return (max(0, col_x1), max(0, col_y1), col_x2, col_y2)
    except Exception as e:
        log.warning("_body_column_bounds failed: %s", e)
        return None


def _trim_to_content(img: Image.Image, min_dark: int = 8, padding: int = 4) -> Image.Image:
    """
    Crop away edge columns/rows that contain fewer than `min_dark` dark pixels.
    Grid lines and page borders are 1–2px wide with very few dark pixels per row/col;
    the body silhouette has many more.  This removes table chrome that _auto_trim misses.
    """
    arr = np.array(img.convert('RGB'))
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    dark = (r < 80) & (g < 80) & (b < 80)
    col_counts = dark.sum(axis=0)
    row_counts = dark.sum(axis=1)
    content_cols = np.where(col_counts >= min_dark)[0]
    content_rows = np.where(row_counts >= min_dark)[0]
    if len(content_cols) == 0 or len(content_rows) == 0:
        return img
    c0 = max(0, int(content_cols[0]) - padding)
    c1 = min(img.width,  int(content_cols[-1]) + padding + 1)
    r0 = max(0, int(content_rows[0]) - padding)
    r1 = min(img.height, int(content_rows[-1]) + padding + 1)
    if c1 <= c0 or r1 <= r0:
        return img
    return img.crop((c0, r0, c1, r1))


def render_totalbody_bone_overlay(bone_xps: str, dpi: int = 200) -> 'Image.Image | None':
    """
    Render Full_body.xps with mutool (preserving XAML ROI region boxes — the
    Head / Arms / Legs / Trunk / Ribs / Pelvis / Spine region outlines drawn
    over the body silhouette), then crop to just the body column.

    Raw strip stitching cannot capture these vector overlays; this function
    produces the image that shows the body with its bone-density ROI regions.

    Returns None if mutool is unavailable or bounds cannot be determined.
    """
    from parse_xps import render_xps_pages, _bounds_to_png

    bounds = _body_column_bounds(bone_xps)
    if bounds is None:
        log.warning("render_totalbody_bone_overlay: body column bounds unavailable")
        return None

    pages = render_xps_pages(bone_xps, dpi=dpi)
    if not pages:
        log.info("render_totalbody_bone_overlay: mutool unavailable — skipping ROI overlay")
        return None

    try:
        png_bytes = _bounds_to_png(pages[0], bounds, dpi, label='bone_roi')
        img = Image.open(io.BytesIO(png_bytes)).convert('RGB')
        return _trim_to_content(img)
    except Exception as e:
        log.warning("render_totalbody_bone_overlay crop failed: %s", e)
        return None


def extract_totalbody_images(bone_xps: str, comp_xps: str = None) -> dict:
    """
    Extract key images from total-body XPS files.

    Args:
        bone_xps: path to Full_body.xps
        comp_xps: path to Full_body-1.xps (optional)

    Returns:
        {
          'body_silhouette': PIL.Image  (left column of Full_body.xps)
          'bmd_chart':       PIL.Image  (right column of Full_body.xps)
          'comp_chart':      PIL.Image  (Full_body-1.xps, optional)
        }
    """
    result = {}

    # ── Full_body.xps — two-column layout ─────────────────────────────
    try:
        with zipfile.ZipFile(bone_xps) as zf:
            fpage = zf.read('Documents/1/Pages/1.fpage').decode('utf-8')

            entries = []
            for data, src in _IMGBRUSH_RE.findall(fpage):
                m = _RECT_RE.match(data.strip())
                if not m:
                    continue
                pts = [float(x) for x in m.groups()]
                x1 = pts[0]
                num = int(re.search(r'(\d+)\.PNG', src).group(1))
                entries.append((x1, num))

            # Two columns separated by x-position
            x_vals = sorted({round(x, 0) for x, _ in entries})
            left_x = x_vals[0] if x_vals else 0

            left_nums  = sorted(num for x, num in entries if round(x, 0) == left_x)
            right_nums = sorted(num for x, num in entries if round(x, 0) != left_x)

            def _load_strips(nums):
                strips = []
                available = {n for n in zf.namelist() if 'Images/' in n}
                for n in nums:
                    p = f'Documents/1/Resources/Images/{n}.PNG'
                    if p in available:
                        try:
                            strips.append(Image.open(io.BytesIO(zf.read(p))))
                        except Exception:
                            pass
                return strips

            left_img  = _stitch_raw(_load_strips(left_nums))  if left_nums  else None
            right_img = _stitch_raw(_load_strips(right_nums)) if right_nums else None

            def _is_soft_tissue(img: Image.Image) -> bool:
                """
                Soft-tissue image has predominantly dark non-background pixels
                (fat tissue has low X-ray attenuation → dark).
                Bone scan has many bright pixels (bones are dense → bright).
                Median intensity of non-background pixels < 100 → soft tissue.
                """
                arr = np.array(img.convert('L'), dtype=np.float32)
                non_bg = arr[arr < 238]
                if len(non_bg) == 0:
                    return True
                return float(np.median(non_bg)) < 100

            if left_img and right_img:
                if _is_soft_tissue(left_img):
                    result['body_silhouette'] = left_img
                    result['bmd_chart']        = right_img
                else:
                    result['body_silhouette'] = right_img
                    result['bmd_chart']        = left_img
            elif left_img:
                result['body_silhouette'] = left_img
            elif right_img:
                result['bmd_chart'] = right_img

        log.info("extract_totalbody_images: bone silhouette=%s bmd_chart=%s",
                 result.get('body_silhouette', {}) and result['body_silhouette'].size,
                 result.get('bmd_chart', {}) and result['bmd_chart'].size)
    except Exception as e:
        log.warning("extract_totalbody_images bone XPS failed: %s", e)

    # ── Full_body-1.xps — single-column composition chart ─────────────
    if comp_xps:
        try:
            with zipfile.ZipFile(comp_xps) as zf:
                fpage = zf.read('Documents/1/Pages/1.fpage').decode('utf-8')

                nums = sorted(
                    int(re.search(r'(\d+)\.PNG', src).group(1))
                    for _, src in _IMGBRUSH_RE.findall(fpage)
                    if re.search(r'(\d+)\.PNG', src)
                )
                available = {n for n in zf.namelist() if 'Images/' in n}
                strips = []
                for n in nums:
                    p = f'Documents/1/Resources/Images/{n}.PNG'
                    if p in available:
                        try:
                            strips.append(Image.open(io.BytesIO(zf.read(p))))
                        except Exception:
                            pass
                if strips:
                    result['comp_chart'] = _stitch_raw(strips)
            log.info("extract_totalbody_images: comp_chart=%s",
                     result.get('comp_chart') and result['comp_chart'].size)
        except Exception as e:
            log.warning("extract_totalbody_images comp XPS failed: %s", e)

    return result
