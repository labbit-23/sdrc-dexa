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
from collections import defaultdict
from typing import Optional

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

log = logging.getLogger(__name__)

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
                results[label] = _stitch_and_colorise(strips)
            else:
                log.warning("No usable strips found for %s in %s", label, xps_path)
    return results


def _stitch_and_colorise(strips: list[Image.Image]) -> Image.Image:
    """Stack strips vertically, crop white borders, apply false-colour DEXA map."""
    total_h = sum(s.height for s in strips)
    w = strips[0].width
    full = Image.new('RGB', (w, total_h), (255, 255, 255))
    y = 0
    for s in strips:
        full.paste(s, (0, y))
        y += s.height
    return _crop_and_colorise(full)


def _crop_and_colorise(img: Image.Image) -> Image.Image:
    arr = np.array(img)

    # Crop white borders
    mask = ~((arr[:, :, 0] > 238) & (arr[:, :, 1] > 238) & (arr[:, :, 2] > 238))
    rows, cols = np.any(mask, axis=1), np.any(mask, axis=0)
    if rows.any():
        r0, r1 = int(np.where(rows)[0][0]), int(np.where(rows)[0][-1])
        c0, c1 = int(np.where(cols)[0][0]), int(np.where(cols)[0][-1])
        pad = 6
        img = img.crop((
            max(0, c0 - pad), max(0, r0 - pad),
            min(img.width, c1 + pad), min(img.height, r1 + pad),
        ))
        arr = np.array(img)

    gray = np.array(img.convert('L'), dtype=float)
    h, w = gray.shape
    out = np.zeros((h, w, 3), dtype=np.uint8)

    # background → near-black
    out[gray < 22] = [8, 14, 24]

    # soft tissue → warm red gradient
    m = (gray >= 22) & (gray < 80)
    t = ((gray[m] - 22) / 58.0).clip(0, 1)
    out[m, 0] = (185 + 55 * t).clip(0, 255).astype(np.uint8)
    out[m, 1] = (65  + 35 * t).clip(0, 255).astype(np.uint8)
    out[m, 2] = (50  + 25 * t).clip(0, 255).astype(np.uint8)

    # lean / muscle → teal gradient
    m = (gray >= 80) & (gray < 165)
    t = ((gray[m] - 80) / 85.0).clip(0, 1)
    out[m, 0] = (12  + 50 * t).clip(0, 255).astype(np.uint8)
    out[m, 1] = (148 + 72 * t).clip(0, 255).astype(np.uint8)
    out[m, 2] = (162 + 65 * t).clip(0, 255).astype(np.uint8)

    # bone → near-white
    m = gray >= 165
    t = ((gray[m] - 165) / 90.0).clip(0, 1)
    out[m, 0] = (188 + 67 * t).clip(0, 255).astype(np.uint8)
    out[m, 1] = (218 + 37 * t).clip(0, 255).astype(np.uint8)
    out[m, 2] = (228 + 27 * t).clip(0, 255).astype(np.uint8)

    result = Image.fromarray(out, 'RGB')
    result = ImageEnhance.Contrast(result).enhance(1.35)
    result = result.filter(ImageFilter.UnsharpMask(radius=1, percent=120, threshold=3))
    return result


def _colorise_bone_density(img: Image.Image) -> Image.Image:
    """Pass-through — return the image exactly as extracted from the XPS."""
    return img.convert('RGB')


def _stitch_bone_density(strips: list[Image.Image]) -> Image.Image:
    """Stitch + crop + apply bone-density colormap."""
    total_h = sum(s.height for s in strips)
    w = strips[0].width
    full = Image.new('RGB', (w, total_h), (255, 255, 255))
    y = 0
    for s in strips:
        full.paste(s.convert('RGB'), (0, y))
        y += s.height

    # Crop near-white margins (scanner background is 250–255)
    arr = np.array(full)
    # Signal = pixels darker than 230 (bone/soft-tissue regions)
    mask = arr.mean(axis=2) < 230
    rows, cols = np.any(mask, axis=1), np.any(mask, axis=0)
    if rows.any():
        r0, r1 = int(np.where(rows)[0][0]), int(np.where(rows)[0][-1])
        c0, c1 = int(np.where(cols)[0][0]), int(np.where(cols)[0][-1])
        pad = 12
        full = full.crop((
            max(0, c0 - pad), max(0, r0 - pad),
            min(full.width, c1 + pad), min(full.height, r1 + pad),
        ))

    return _colorise_bone_density(full)


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
    return _stitch_bone_density(strips)


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

    # ── Combined XPS: all labels point to the same file ──────────────────────
    unique_paths = {p for p in paths.values() if p}
    if len(unique_paths) == 1:
        combined_path = next(iter(unique_paths))
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


# ── XPS type detection ────────────────────────────────────────────────────
_TB_COMPOSITION_RE = re.compile(
    r'%\s*Fat|Android\s*%|Gynoid|Lean\s+Mass', re.IGNORECASE
)
_TB_BONE_REGION_RE = re.compile(
    r'(?:Pelvis|Trunk|Ribs)\s+[\d.]+\s+[\d.]+', re.IGNORECASE
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

    # Spine+femur: has at least 2 "Densitometry Reference:" sections
    # (spine + left femur + right femur = 3). Total-body bone has exactly 1
    # ("Densitometry Reference: Total").
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
