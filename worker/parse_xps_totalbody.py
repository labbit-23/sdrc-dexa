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

_REGION_RE    = re.compile(r'(Head|Arms|Legs|Trunk|Ribs|Pelvis|Spine)-\s*([\d.]+)\s*-')
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

            if left_nums:
                result['body_silhouette'] = _stitch_raw(_load_strips(left_nums))
            if right_nums:
                result['bmd_chart'] = _stitch_raw(_load_strips(right_nums))

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
