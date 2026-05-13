"""
Clinical DEXA Total Body Composition report — ReportLab renderer.

7 pages:
  1 — Body Composition Summary   (colorized silhouette + metric circles)
  2 — Body Fat Scale             (gradient bar + legend + gradient silhouette)
  3 — Metabolic Rate             (RMR from Katch-McArdle + TDEE table)
  4 — Regional Analysis          (silhouette + per-region table + bar chart)
  5 — Android-Gynoid Ratio       (A/G box + bars + reference table)
  6 — Bone Health                (BMD table + T-score bars + bone image)
  7 — Clinical Recommendations

Entry point: render_totalbody_pdf(report_data: dict) -> bytes
"""

import io
import urllib.request
from datetime import datetime

from reportlab.lib.colors import HexColor, white, black
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas
from reportlab.platypus import Table, TableStyle

import config
from render_pdf import W, H, MARGIN, CONTENT_W, _pil_to_rl, classify
from parse_xps_totalbody import colorize_dexa_silhouette

# ── Colour palette ─────────────────────────────────────────────────────────────
PINK  = HexColor('#E91E8C')
LPINK = HexColor('#FCE4EC')
CYAN  = HexColor('#00BCD4')
LCYAN = HexColor('#E0F7FA')
TEAL  = HexColor('#0D7377')
DARK  = HexColor('#0D1B2A')
DGRAY = HexColor('#616161')
MGRAY = HexColor('#9E9E9E')
LGRAY = HexColor('#F5F5F5')
GREEN = HexColor('#2E7D32')
LGREEN= HexColor('#C8E6C9')
AMBER = HexColor('#E65100')
LAMBER= HexColor('#FFF9C4')
RED   = HexColor('#B71C1C')
LRED  = HexColor('#FFCDD2')

BONE_ORDER   = ['Head', 'Arms', 'Legs', 'Trunk', 'Ribs', 'Pelvis', 'Spine', 'Total']
REGION_ORDER = ['Trunk', 'Android', 'Arms', 'Gynoid', 'Legs']

# ── Render mode ────────────────────────────────────────────────────────────────
_render_mode = 'screen'

# Print-mode layout: leave top 43mm for letterhead, bottom 22mm for footer
_CONTENT_TOP_PRINT = H - 43 * mm - 14
_FOOTER_TOP_PRINT  = 22 * mm


def _is_print() -> bool:
    return _render_mode == 'print'


def _panel_bg() -> HexColor:
    return LGRAY if _is_print() else DARK


def _panel_fg() -> HexColor:
    return DARK if _is_print() else white


def _content_top() -> float:
    return _CONTENT_TOP_PRINT if _is_print() else _CONTENT_TOP


def _footer_top() -> float:
    return _FOOTER_TOP_PRINT if _is_print() else _FOOTER_TOP


# ── Logo cache (fetched once per process) ──────────────────────────────────────
_logo_rl      = None
_logo_fetched = False


def _get_logo_rl():
    global _logo_rl, _logo_fetched
    if _logo_fetched:
        return _logo_rl
    _logo_fetched = True
    try:
        url = 'https://www.sdrc.in/assets/sdrc-logo-full.png'
        with urllib.request.urlopen(url, timeout=3) as resp:
            data = resp.read()
        from PIL import Image as PILImage
        _logo_rl = _pil_to_rl(PILImage.open(io.BytesIO(data)))
    except Exception:
        _logo_rl = None
    return _logo_rl


# ── Fat category thresholds ────────────────────────────────────────────────────
_FAT_CATS_F = [
    (0,  14,  HexColor('#00BCD4'), "LOW BODY FAT RISK",
     "Ask your physician about how to safely\nincrease your body fat"),
    (14, 21,  HexColor('#4FC3F7'), "ULTRA LEAN",
     "Body fat often found in elite female athletes"),
    (21, 28,  HexColor('#1565C0'), "LEAN",
     "Lower than most people —\nexcellent for health"),
    (28, 35,  HexColor('#7B1FA2'), "MODERATE",
     "Average body fat for your age group"),
    (35, 40,  HexColor('#E91E8C'), "EXCESS FAT",
     "Some excess fat stored —\nlifestyle changes advised"),
    (40, 100, HexColor('#C62828'), "HIGH BODY FAT RISK",
     "Consult your healthcare provider about\nsafely reducing body fat"),
]
_FAT_CATS_M = [
    (0,   6,  HexColor('#00BCD4'), "LOW BODY FAT RISK",
     "Ask your physician about how to safely\nincrease your body fat"),
    (6,  13,  HexColor('#4FC3F7'), "ULTRA LEAN",
     "Body fat often found in elite male athletes"),
    (13, 18,  HexColor('#1565C0'), "LEAN",
     "Lower than most people —\nexcellent for health"),
    (18, 25,  HexColor('#7B1FA2'), "MODERATE",
     "Average body fat for your age group"),
    (25, 32,  HexColor('#E91E8C'), "EXCESS FAT",
     "Some excess fat stored —\nlifestyle changes advised"),
    (32, 100, HexColor('#C62828'), "HIGH BODY FAT RISK",
     "Consult your healthcare provider about\nsafely reducing body fat"),
]
_AGE_AVG = {
    'f': {(20,30):28, (30,40):32, (40,50):35, (50,60):38, (60,100):40},
    'm': {(20,30):18, (30,40):22, (40,50):25, (50,60):27, (60,100):29},
}


def _fat_cats(gender):
    return _FAT_CATS_F if 'f' in gender.lower() else _FAT_CATS_M

def _fat_max(gender):
    return 60.0 if 'f' in gender.lower() else 45.0

def _fat_category(pct, gender):
    for lo, hi, col, name, _ in _fat_cats(gender):
        if pct <= hi:
            return col, name
    cats = _fat_cats(gender)
    return cats[-1][2], cats[-1][3]

def _age_avg(age_str, gender):
    try:
        age = float(age_str)
    except Exception:
        age = 45
    g = 'f' if 'f' in gender.lower() else 'm'
    for (lo, hi), avg in _AGE_AVG[g].items():
        if lo <= age < hi:
            return avg
    return 35 if g == 'f' else 25

def _scan_date_str(patient):
    d = patient.get('scan_date_str', '')
    if d:
        try:
            return datetime.strptime(d, '%d-%m-%Y').strftime('%-d %b, %Y')
        except Exception:
            return d
    sd = patient.get('scan_date')
    if sd and hasattr(sd, 'strftime'):
        return sd.strftime('%-d %b, %Y')
    return ''


# ── Text utilities ─────────────────────────────────────────────────────────────

def _wrap(text, font_name, font_size, max_w):
    lines = []
    for para in text.split('\n'):
        words = para.split()
        if not words:
            lines.append('')
            continue
        cur = []
        for word in words:
            test = ' '.join(cur + [word])
            if stringWidth(test, font_name, font_size) > max_w and cur:
                lines.append(' '.join(cur))
                cur = [word]
            else:
                cur.append(word)
        if cur:
            lines.append(' '.join(cur))
    return lines


def _draw_text_box(c, x, y, w, h, title, body,
                   bg=None, title_col=None, body_col=None,
                   border_col=None, title_size=7, body_size=6.5,
                   padding=3):
    bg_c     = bg         or LGRAY
    title_c  = title_col  or DARK
    body_c   = body_col   or DGRAY
    border_c = border_col or MGRAY

    c.setFillColor(bg_c)
    c.setStrokeColor(border_c)
    c.setLineWidth(0.4)
    c.roundRect(x, y, w, h, 2, fill=1, stroke=1)

    inner_w = w - 2 * padding * mm
    gap     = 3 * mm
    title_line_h = title_size * 1.4

    c.setFillColor(title_c)
    c.setFont('Helvetica-Bold', title_size)
    c.drawString(x + padding * mm, y + h - gap - title_size, title)

    text_top = y + h - gap - title_size - title_line_h
    c.setFillColor(body_c)
    c.setFont('Helvetica', body_size)
    line_h = body_size * 1.35
    for line in _wrap(body, 'Helvetica', body_size, inner_w):
        if text_top < y + 2 * mm:
            break
        c.drawString(x + padding * mm, text_top, line)
        text_top -= line_h


# ── Shared header / footer ─────────────────────────────────────────────────────

def _header(c, subtitle):
    if _is_print():
        # Letterhead has SDRC logo top-left; put our title to the right of it
        title_x = MARGIN + 40 * mm
        c.setFillColor(DARK)
        c.setFont('Helvetica-Bold', 13)
        c.drawString(title_x, H - 30 * mm, "DEXA BODY COMPOSITION")
        c.setFillColor(TEAL)
        c.setFont('Helvetica-Bold', 9)
        c.drawString(title_x, H - 37 * mm, subtitle.upper())
        c.setStrokeColor(TEAL)
        c.setLineWidth(1)
        c.line(MARGIN, H - 41 * mm, W - MARGIN, H - 41 * mm)
    else:
        # Screen: title left, logo right (no overlap)
        rl_logo = _get_logo_rl()
        if rl_logo:
            logo_h = 11 * mm
            logo_w = 30 * mm
            c.drawImage(rl_logo,
                        W - MARGIN - logo_w, H - MARGIN - logo_h + 2,
                        width=logo_w, height=logo_h,
                        preserveAspectRatio=True, mask='auto')

        c.setFillColor(black)
        c.setFont('Helvetica-Bold', 22)
        c.drawString(MARGIN, H - MARGIN - 18, "DEXA BODY COMPOSITION")
        c.setFillColor(TEAL)
        c.setFont('Helvetica-Bold', 13)
        c.drawString(MARGIN, H - MARGIN - 34, subtitle)
        c.setStrokeColor(TEAL)
        c.setLineWidth(1)
        c.line(MARGIN, H - MARGIN - 42, W - MARGIN, H - MARGIN - 42)


_CONTENT_TOP = H - MARGIN - 50   # 8pt gap below rule


def _footer(c):
    if _is_print():
        return
    c.setFillColor(LGRAY)
    c.rect(0, 0, W, 12 * mm, fill=1, stroke=0)
    c.setStrokeColor(MGRAY)
    c.setLineWidth(0.4)
    c.line(0, 12 * mm, W, 12 * mm)
    c.setFillColor(DGRAY)
    c.setFont('Helvetica', 6.5)
    c.drawString(MARGIN, 8 * mm, f"{config.CLINIC_NAME}  •  {config.CLINIC_ADDRESS}")
    c.drawString(MARGIN, 4 * mm, f"Scanner: {config.SCANNER_ID}  •  {config.SOFTWARE}")
    c.setFillColor(DARK)
    c.setFont('Helvetica-Bold', 12)
    c.drawRightString(W - MARGIN, 4.5 * mm, "SDRC DIAGNOSTICS")


_FOOTER_TOP = 14 * mm


def _draw_image_scaled(c, img, x, y_bottom, max_w, max_h):
    if img is None:
        return 0, 0
    iw, ih = img.size
    scale = min(max_w / iw, max_h / ih)
    dw, dh = iw * scale, ih * scale
    rl = _pil_to_rl(img)
    if rl:
        cx = x + (max_w - dw) / 2
        c.drawImage(rl, cx, y_bottom, width=dw, height=dh)
    return dw, dh


# ── Page 1: Body Composition Summary ──────────────────────────────────────────

def _page1(c, data):
    patient = data.get('patient') or {}
    comp    = data.get('composition') or {}
    images  = data.get('scan_images') or {}

    date_str = _scan_date_str(patient)
    _header(c, f"Body Composition Summary  –  {date_str}")

    y = _content_top()

    # Patient info box
    BOX_H  = 22 * mm
    fat_pct = comp.get('fat_pct') or 0
    gender  = patient.get('gender', 'Female')

    c.setStrokeColor(TEAL)
    c.setLineWidth(1)
    c.rect(MARGIN, y - BOX_H, CONTENT_W, BOX_H, fill=0, stroke=1)

    BADGE_W = 34 * mm
    bx = MARGIN + CONTENT_W - BADGE_W
    c.setFillColor(PINK)
    c.rect(bx, y - BOX_H, BADGE_W, BOX_H, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont('Helvetica', 7)
    c.drawCentredString(bx + BADGE_W / 2, y - 6 * mm, "Body Fat")
    c.setFont('Helvetica-Bold', 20)
    c.drawCentredString(bx + BADGE_W / 2, y - 15 * mm, f"{fat_pct:.1f} %")

    name  = f"{patient.get('title','').strip()} {patient.get('name','').strip()}".strip()
    age   = patient.get('age_str', '') or ''
    h_cm  = patient.get('height_cm', '') or ''
    w_kg  = patient.get('weight_kg', '') or comp.get('total_kg', '') or ''
    c.setFillColor(DARK)
    c.setFont('Helvetica', 8.5)
    c.drawString(MARGIN + 3 * mm, y - 7 * mm,  f"Name:   {name}")
    c.drawString(MARGIN + 3 * mm, y - 14 * mm, f"Height: {h_cm} cm")
    c.drawString(MARGIN + 72 * mm, y - 7 * mm,  f"Age:  {age} yrs")
    c.drawString(MARGIN + 72 * mm, y - 14 * mm, f"Weight: {w_kg} kg")
    c.drawString(MARGIN + 135 * mm, y - 7 * mm, f"Gender: {gender}")

    y -= BOX_H + 4 * mm

    age_avg = _age_avg(age, gender)
    c.setFillColor(DARK)
    c.setFont('Helvetica-Bold', 8.5)
    c.drawString(MARGIN, y, f"AGE GROUP AVERAGE  {age_avg}%")
    c.setFillColor(DGRAY)
    c.setFont('Helvetica-Oblique', 7)
    c.drawString(MARGIN + 60 * mm, y, "Average body fat % for people in your age group")
    c.setFont('Helvetica', 7)
    c.drawRightString(W - MARGIN, y, "This is your % of body weight made up of fat")

    y -= 10 * mm

    col_gap = 4 * mm
    left_w  = CONTENT_W * 0.40
    right_w = CONTENT_W - left_w - col_gap
    right_x = MARGIN + left_w + col_gap
    col_h   = y - _footer_top()

    raw_comp = images.get('bmd_chart')
    if raw_comp:
        colored = colorize_dexa_silhouette(raw_comp, mode='fat_lean')
        _draw_image_scaled(c, colored, MARGIN, _footer_top(), left_w, col_h)
    c.setFillColor(MGRAY)
    c.setFont('Helvetica-Oblique', 5.5)
    c.drawCentredString(MARGIN + left_w / 2, _footer_top() - 1, "Image not for diagnosis")

    panel_bg = _panel_bg()
    c.setFillColor(panel_bg)
    if _is_print():
        c.setStrokeColor(TEAL)
        c.setLineWidth(0.8)
        c.roundRect(right_x, _footer_top(), right_w, col_h, 3, fill=1, stroke=1)
    else:
        c.roundRect(right_x, _footer_top(), right_w, col_h, 3, fill=1, stroke=0)

    c.setFillColor(_panel_fg())
    c.setFont('Helvetica-Bold', 7)
    c.drawCentredString(right_x + right_w / 2, y - 7 * mm,
                        "YOUR BODY COMPOSITION AND WHAT IT MEANS")

    total_kg = comp.get('total_kg') or 0
    lean_kg  = round((comp.get('lean_g') or 0) / 1000, 1)
    fat_kg   = round((comp.get('fat_g')  or 0) / 1000, 1)
    bmc_kg   = round((comp.get('bmc_g')  or 0) / 1000, 2)

    metrics = [
        (f"{total_kg}", "kgs", "TOTAL MASS",   CYAN,
         "The total weight of your body.\nIncludes fat, lean, water\nand bone minerals."),
        (f"{lean_kg}",  "kgs", "LEAN MASS",    CYAN,
         "Weight of your muscles, bones,\nligaments, water & organs.\nIncrease via strength training\n& adequate protein."),
        (f"{fat_kg}",   "kgs", "FAT MASS",     PINK,
         "The portion of your body\nthat is strictly fat.\nDecrease via nutrition\nplanning & cardio."),
        (f"{bmc_kg}",   "kgs", "BONE MINERAL", MGRAY,
         "Weight of bone minerals\nin your skeletal structure.\nEnsure adequate Calcium\n& Vitamin D."),
    ]

    panel_inner_top = y - 12 * mm
    panel_inner_h   = panel_inner_top - _footer_top() - 4 * mm
    slot_h  = panel_inner_h / 4
    CIRC_R  = min(slot_h * 0.22, 11 * mm)
    circ_x  = right_x + right_w * 0.28

    _divider_col = HexColor('#CCCCCC') if _is_print() else HexColor('#1a2f45')

    for i, (val, unit, label, col, tip) in enumerate(metrics):
        cy = panel_inner_top - (i + 0.5) * slot_h

        if i > 0:
            c.setStrokeColor(_divider_col)
            c.setLineWidth(0.4)
            c.line(right_x + 3 * mm, cy + slot_h / 2,
                   right_x + right_w - 3 * mm, cy + slot_h / 2)

        c.setStrokeColor(col)
        c.setLineWidth(2)
        c.circle(circ_x, cy, CIRC_R, fill=0, stroke=1)

        val_size = min(CIRC_R * 0.60, 11)
        c.setFillColor(col)
        c.setFont('Helvetica-Bold', val_size)
        c.drawCentredString(circ_x, cy + val_size * 0.15, val)

        _panel_text = _panel_fg()
        c.setFillColor(_panel_text)
        c.setFont('Helvetica', val_size * 0.50)
        c.drawCentredString(circ_x, cy - val_size * 0.55, unit)

        c.setFont('Helvetica-Bold', 5.5)
        c.drawCentredString(circ_x, cy - CIRC_R - 3, label)

        tip_x   = right_x + right_w * 0.50
        tip_max = right_w - (tip_x - right_x) - 3 * mm
        c.setFillColor(_panel_text)
        c.setFont('Helvetica', 6)
        tip_lines = _wrap(tip, 'Helvetica', 6, tip_max)
        tip_y = cy + len(tip_lines) * 7 / 2
        for line in tip_lines[:5]:
            c.drawString(tip_x, tip_y, line)
            tip_y -= 7

    _footer(c)


# ── Page 2: Body Fat Scale ─────────────────────────────────────────────────────

def _page2(c, data):
    patient = data.get('patient') or {}
    comp    = data.get('composition') or {}
    images  = data.get('scan_images') or {}

    _header(c, "Body Fat Scale")

    fat_pct  = comp.get('fat_pct') or 0
    gender   = patient.get('gender', 'Female')
    date_str = _scan_date_str(patient)
    fat_max  = _fat_max(gender)
    cats     = _fat_cats(gender)

    y = _content_top()

    c.setFillColor(DARK)
    c.setFont('Helvetica', 8.5)
    c.drawString(MARGIN, y, "RECOMMENDED  ")
    c.setFont('Helvetica-Bold', 8.5)
    c.drawString(MARGIN + 30 * mm, y, "FOLLOW-UP")
    c.setFont('Helvetica', 8.5)
    c.drawString(MARGIN + 55 * mm, y, "— Repeat in 24 months")
    y -= 14 * mm

    mk_x = MARGIN + (min(fat_pct, fat_max) / fat_max) * CONTENT_W
    c.setFillColor(DARK)
    c.setFont('Helvetica-Bold', 10)
    c.drawCentredString(mk_x, y, f"{fat_pct:.1f}")
    y -= 5 * mm

    c.setFillColor(DARK)
    path = c.beginPath()
    path.moveTo(mk_x - 5, y)
    path.lineTo(mk_x + 5, y)
    path.lineTo(mk_x, y - 5)
    path.close()
    c.drawPath(path, fill=1, stroke=0)
    y -= 2 * mm

    BAR_H = 12 * mm
    for lo, hi, col, *_ in cats:
        lo_c = min(lo, fat_max)
        hi_c = min(hi, fat_max)
        bx   = MARGIN + (lo_c / fat_max) * CONTENT_W
        bw   = ((hi_c - lo_c) / fat_max) * CONTENT_W
        c.setFillColor(col)
        c.rect(bx, y - BAR_H, bw, BAR_H, fill=1, stroke=0)

    c.setFillColor(DARK)
    c.setFont('Helvetica', 7.5)
    c.drawString(MARGIN, y - BAR_H - 4 * mm, "0")
    c.drawRightString(W - MARGIN, y - BAR_H - 4 * mm, f"{int(fat_max)}")
    y -= BAR_H + 10 * mm

    # 6-category legend
    c.setFillColor(DARK)
    c.setFont('Helvetica-Bold', 7.5)
    c.drawString(MARGIN, y, "BODY FAT")
    c.setFont('Helvetica', 7)
    c.drawString(MARGIN, y - 5 * mm, "SCALE")

    LGND_X0 = MARGIN + 16 * mm
    LGND_W  = CONTENT_W - 16 * mm
    lcw     = LGND_W / 3
    ROW_H   = 28 * mm

    for i, (lo, hi, col, name, desc) in enumerate(cats):
        row = i // 3
        cx  = LGND_X0 + (i % 3) * lcw
        cy  = y - row * ROW_H

        c.setFillColor(col)
        c.rect(cx, cy - 2.5 * mm, 8 * mm, 3.5 * mm, fill=1, stroke=0)

        c.setFillColor(DARK)
        c.setFont('Helvetica-Bold', 7)
        c.drawString(cx + 10 * mm, cy - 1 * mm, name)

        c.setFillColor(DGRAY)
        c.setFont('Helvetica', 6.5)
        desc_y = cy - 6.5 * mm
        for line in _wrap(desc, 'Helvetica', 6.5, lcw - 12 * mm):
            c.drawString(cx + 10 * mm, desc_y, line)
            desc_y -= 8

    y -= 2 * ROW_H + 14 * mm

    avail_h = y - _footer_top()
    avail_w = CONTENT_W * 0.45

    c.saveState()
    c.translate(MARGIN - 4 * mm, y - avail_h / 2)
    c.rotate(90)
    c.setFillColor(DARK)
    c.setFont('Helvetica-Bold', 8)
    c.drawCentredString(0, 0, "X-RAY TRENDS")
    c.restoreState()

    raw_comp = images.get('bmd_chart') if images else None
    if raw_comp:
        fat_sil = colorize_dexa_silhouette(raw_comp, mode='fat_gradient')
        img_x = MARGIN + (CONTENT_W - avail_w) / 2
        dw, dh = _draw_image_scaled(c, fat_sil, img_x, _footer_top(), avail_w, avail_h)
        if dh > 0:
            c.setFillColor(DARK)
            c.setFont('Helvetica-Bold', 7.5)
            c.drawCentredString(img_x + avail_w / 2, _footer_top() - 1, date_str)
    else:
        c.setFillColor(MGRAY)
        c.setFont('Helvetica-Oblique', 8)
        c.drawCentredString(W / 2, y - avail_h / 2, "Scan image not available")

    _footer(c)


# ── Page 3: Metabolic Rate ─────────────────────────────────────────────────────

def _page3_rmr(c, data):
    patient = data.get('patient') or {}
    comp    = data.get('composition') or {}

    _header(c, "Metabolic Rate Analysis")

    lean_g   = comp.get('lean_g') or 0
    lean_kg  = lean_g / 1000
    fat_pct  = comp.get('fat_pct') or 0
    total_kg = comp.get('total_kg') or 0
    gender   = patient.get('gender', 'Female')
    age_str  = patient.get('age_str', '45') or '45'

    # Katch-McArdle formula (lean-mass based, gender-independent)
    rmr = 370 + 21.6 * lean_kg if lean_kg > 0 else 0

    y = _content_top()

    # ── Top band: RMR value ───────────────────────────────────────────────────
    BAND_H = 38 * mm
    c.setFillColor(_panel_bg())
    c.roundRect(MARGIN, y - BAND_H, CONTENT_W, BAND_H, 3, fill=1, stroke=0)
    if _is_print():
        c.setStrokeColor(TEAL)
        c.setLineWidth(0.8)
        c.roundRect(MARGIN, y - BAND_H, CONTENT_W, BAND_H, 3, fill=0, stroke=1)

    # Large RMR number left of center
    RMR_X = MARGIN + CONTENT_W * 0.28
    c.setFillColor(CYAN)
    c.setFont('Helvetica-Bold', 8)
    c.drawCentredString(RMR_X, y - 10 * mm, "RESTING METABOLIC RATE")
    c.setFont('Helvetica-Bold', 36)
    c.drawCentredString(RMR_X, y - 26 * mm, f"{int(rmr):,}")
    c.setFont('Helvetica', 10)
    c.drawCentredString(RMR_X, y - 33 * mm, "kcal / day")

    # Right: context numbers
    ctx_x = MARGIN + CONTENT_W * 0.52
    ctx_w = CONTENT_W * 0.44
    ctx_items = [
        (f"{lean_kg:.1f} kg", "Lean Mass",   CYAN),
        (f"{fat_pct:.1f}%",   "Body Fat",    PINK),
        (f"{total_kg} kg",    "Total Weight", _panel_fg()),
    ]
    ctx_col_w = ctx_w / 3
    for i, (val, lbl, col) in enumerate(ctx_items):
        cx = ctx_x + (i + 0.5) * ctx_col_w
        if i > 0:
            c.setStrokeColor(HexColor('#CCCCCC') if _is_print() else HexColor('#1a2f45'))
            c.setLineWidth(0.4)
            c.line(ctx_x + i * ctx_col_w, y - 10 * mm,
                   ctx_x + i * ctx_col_w, y - 35 * mm)
        c.setFillColor(col)
        c.setFont('Helvetica-Bold', 15)
        c.drawCentredString(cx, y - 22 * mm, val)
        c.setFillColor(_panel_fg())
        c.setFont('Helvetica', 7)
        c.drawCentredString(cx, y - 29 * mm, lbl)

    y -= BAND_H + 8 * mm

    # ── What is RMR? explanation ──────────────────────────────────────────────
    c.setFillColor(DARK)
    c.setFont('Helvetica-Bold', 9)
    c.drawString(MARGIN, y, "WHAT IS RESTING METABOLIC RATE?")
    y -= 5 * mm

    expl = ("Your Resting Metabolic Rate (RMR) is the number of calories your body burns "
            "every day just to keep you alive — breathing, circulation, organ function — "
            "without any physical activity. It is calculated from your lean mass using the "
            "Katch-McArdle formula: RMR = 370 + (21.6 × lean body mass in kg). "
            "The more lean muscle you carry, the higher your metabolic rate.")
    c.setFillColor(DGRAY)
    c.setFont('Helvetica', 7.5)
    line_h = 10
    for line in _wrap(expl, 'Helvetica', 7.5, CONTENT_W):
        c.drawString(MARGIN, y, line)
        y -= line_h
    y -= 4 * mm

    # ── Activity multiplier table ─────────────────────────────────────────────
    c.setFillColor(DARK)
    c.setFont('Helvetica-Bold', 9)
    c.drawString(MARGIN, y, "TOTAL DAILY ENERGY EXPENDITURE  (TDEE)")
    y -= 4 * mm

    c.setFillColor(DGRAY)
    c.setFont('Helvetica', 7)
    c.drawString(MARGIN, y,
                 "Multiply your RMR by your typical activity level to get your daily calorie needs.")
    y -= 6 * mm

    act_levels = [
        ("Sedentary",    "Little to no exercise",                         1.20),
        ("Lightly Active","Light exercise 1–3 days/week",                  1.375),
        ("Moderately Active","Moderate exercise 3–5 days/week",            1.55),
        ("Very Active",  "Hard exercise 6–7 days/week",                   1.725),
        ("Extremely Active","Physical job + hard training daily",          1.90),
    ]

    hdr_row = ["Activity Level", "Description", "Multiplier", "TDEE (kcal/day)"]
    tbl_rows = [hdr_row] + [
        [name, desc, f"×{mult:.3f}", f"{int(rmr * mult):,}"]
        for name, desc, mult in act_levels
    ]

    col_ws = [CONTENT_W * f for f in [0.22, 0.40, 0.14, 0.24]]
    tstyle = TableStyle([
        ('BACKGROUND',    (0, 0), (-1, 0), DARK),
        ('TEXTCOLOR',     (0, 0), (-1, 0), white),
        ('FONTNAME',      (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE',      (0, 0), (-1, -1), 7.5),
        ('ALIGN',         (2, 0), (-1, -1), 'CENTER'),
        ('ALIGN',         (0, 0), (1, -1),  'LEFT'),
        ('ROWBACKGROUNDS',(0, 1), (-1, -1), [white, LGRAY]),
        ('GRID',          (0, 0), (-1, -1), 0.3, MGRAY),
        ('TOPPADDING',    (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING',   (0, 0), (-1, -1), 5),
        ('FONTNAME',      (-1, 1), (-1, -1), 'Helvetica-Bold'),
        ('TEXTCOLOR',     (-1, 1), (-1, -1), TEAL),
    ])

    tbl = Table(tbl_rows, colWidths=col_ws)
    tbl.setStyle(tstyle)
    _, th = tbl.wrapOn(c, CONTENT_W, 400)
    tbl.drawOn(c, MARGIN, y - th)
    y -= th + 10 * mm

    # ── Three info panels ─────────────────────────────────────────────────────
    panel_w = (CONTENT_W - 2 * 3 * mm) / 3
    panel_h = y - _footer_top()

    panels = [
        ("How lean mass drives metabolism",
         "Muscle tissue is metabolically expensive — it burns calories even at rest. "
         "Each kg of lean mass burns approximately 13 kcal/day. "
         "Strength training preserves and builds lean mass, keeping your RMR elevated as you age."),
        ("Why RMR declines with age",
         "After age 30, adults lose roughly 3–8% of muscle mass per decade (sarcopenia). "
         "This reduces RMR and makes weight gain easier. "
         "Resistance training and adequate protein (1.2–1.6 g/kg/day) are the best countermeasures."),
        ("Using this number",
         "To maintain weight: eat close to your TDEE.\n"
         "To lose fat: aim for a 300–500 kcal deficit below TDEE.\n"
         "To gain muscle: eat 200–300 kcal above TDEE.\n"
         "Never eat below your RMR without medical supervision."),
    ]

    for i, (title, body) in enumerate(panels):
        px = MARGIN + i * (panel_w + 3 * mm)
        border = TEAL if i == 0 else MGRAY
        bg_col = LCYAN if i == 0 else LGRAY
        _draw_text_box(c, px, _footer_top(), panel_w, panel_h,
                       title, body, bg=bg_col, border_col=border,
                       title_col=TEAL if i == 0 else DARK,
                       body_size=6.5)

    _footer(c)


# ── Page 4: Regional Analysis ──────────────────────────────────────────────────

def _page4(c, data):
    patient = data.get('patient') or {}
    comp    = data.get('composition') or {}
    regions = comp.get('regions') or {}
    images  = data.get('scan_images') or {}

    _header(c, "Regional Body Composition")

    y = _content_top()

    # ── Single silhouette + region labels side by side ────────────────────────
    SIL_W  = CONTENT_W * 0.28
    DATA_W = CONTENT_W - SIL_W - 4 * mm
    data_x = MARGIN + SIL_W + 4 * mm
    avail_h = y - _footer_top()

    raw_sil = images.get('body_silhouette')
    if raw_sil:
        colored = colorize_dexa_silhouette(raw_sil, mode='fat_lean')
        _draw_image_scaled(c, colored, MARGIN, _footer_top(), SIL_W, avail_h * 0.82)
    c.setFillColor(MGRAY)
    c.setFont('Helvetica-Oblique', 5.5)
    c.drawCentredString(MARGIN + SIL_W / 2, _footer_top() - 1, "Image not for diagnosis")

    # ── Region names + fat % heading ─────────────────────────────────────────
    c.saveState()
    c.translate(MARGIN - 5 * mm, y - 55 * mm)
    c.rotate(90)
    c.setFillColor(DARK)
    c.setFont('Helvetica-Bold', 8)
    c.drawCentredString(0, 0, "REGIONAL  ANALYSIS")
    c.restoreState()

    n_cols = len(REGION_ORDER)
    col_w  = DATA_W / n_cols

    c.setFillColor(DARK)
    c.setFont('Helvetica-Bold', 8)
    for i, region in enumerate(REGION_ORDER):
        rv      = regions.get(region, {})
        fat_pct = rv.get('fat_pct')
        cx      = data_x + (i + 0.5) * col_w
        c.setFillColor(DARK)
        c.setFont('Helvetica-Bold', 7.5)
        c.drawCentredString(cx, y - 5 * mm, region.upper())
        if fat_pct is not None:
            c.setFillColor(PINK)
            c.setFont('Helvetica-Bold', 8)
            c.drawCentredString(cx, y - 11 * mm, f"{fat_pct:.1f}%")
    y -= 16 * mm

    # ── Data table ───────────────────────────────────────────────────────────
    ROW_H = 7.5 * mm
    row_defs = [
        ('FAT %',  'fat_pct',  '{:.1f} %',  None,  DARK),
        ('TOTAL',  'total_g',  '{:.1f} kg', None,  DARK),
        ('LEAN',   'lean_g',   '{:.2f} kg', CYAN,  white),
        ('FAT',    'fat_g',    '{:.2f} kg', PINK,  white),
        ('BONE',   'bone_g',   '{:.3f} kg', LGRAY, DARK),
    ]

    for row_label, key, fmt, bg, fg in row_defs:
        if bg:
            c.setFillColor(bg)
            c.rect(data_x, y - ROW_H, DATA_W, ROW_H, fill=1, stroke=0)

        c.setFillColor(DARK if bg is None else fg)
        c.setFont('Helvetica-Bold', 7)
        c.drawString(data_x + 1 * mm, y - ROW_H / 2 - 2.5, row_label)

        for i, region in enumerate(REGION_ORDER):
            rv   = regions.get(region, {})
            v    = rv.get(key)
            text = '—' if v is None else fmt.format(
                v / 1000 if key in ('fat_g', 'lean_g', 'bone_g', 'total_g') else v
            )
            cx = data_x + (i + 0.5) * col_w
            c.setFillColor(fg if bg else DARK)
            c.setFont('Helvetica-Bold', 7.5)
            c.drawCentredString(cx, y - ROW_H / 2 - 2.5, text)

        c.setStrokeColor(LGRAY)
        c.setLineWidth(0.4)
        c.line(data_x, y - ROW_H, data_x + DATA_W, y - ROW_H)
        y -= ROW_H

    y -= 6 * mm

    # ── Regional fat% bar chart ───────────────────────────────────────────────
    CHART_H = 34 * mm
    max_pct = 65.0

    c.setFillColor(DARK)
    c.setFont('Helvetica-Bold', 7.5)
    c.drawString(data_x, y, "REGIONAL FAT % COMPARISON")
    y -= 4 * mm

    chart_bottom = y - CHART_H

    for i, region in enumerate(REGION_ORDER):
        rv      = regions.get(region, {})
        fat_pct = rv.get('fat_pct') or 0
        bar_h   = (fat_pct / max_pct) * CHART_H
        bx      = data_x + i * col_w + col_w * 0.15
        bw      = col_w * 0.70

        c.setFillColor(LGRAY)
        c.rect(bx, chart_bottom, bw, CHART_H, fill=1, stroke=0)
        bar_col = PINK if fat_pct > 35 else (HexColor('#7B1FA2') if fat_pct > 28 else CYAN)
        c.setFillColor(bar_col)
        c.rect(bx, chart_bottom, bw, bar_h, fill=1, stroke=0)
        c.setFillColor(DARK)
        c.setFont('Helvetica-Bold', 7)
        c.drawCentredString(bx + bw / 2, chart_bottom + bar_h + 1.5 * mm, f"{fat_pct:.1f}%")

    gender  = patient.get('gender', 'Female')
    age_str = patient.get('age_str', '45') or '45'
    avg_pct = _age_avg(age_str, gender)
    ref_y   = chart_bottom + (avg_pct / max_pct) * CHART_H
    c.setStrokeColor(MGRAY)
    c.setLineWidth(0.8)
    c.setDash(4, 3)
    c.line(data_x, ref_y, data_x + DATA_W, ref_y)
    c.setDash()
    c.setFillColor(MGRAY)
    c.setFont('Helvetica-Oblique', 6)
    c.drawString(data_x + DATA_W + 1 * mm, ref_y - 1, f"avg {avg_pct}%")

    y = chart_bottom - 8 * mm

    # ── Info panels ───────────────────────────────────────────────────────────
    panels = [
        ("Causes of imbalance",
         "Movement and physical function requires a balance between "
         "muscle tone, strength and length. Repeated movements in one "
         "direction or sustained postures can set up a muscle imbalance "
         "that can ultimately lead to joint dysfunction."),
        ("How does it affect you?",
         "Many musculoskeletal conditions are caused by imbalance of "
         "opposing muscles in different regions — commonly in the "
         "Gynoid, Trunk, Android and Lumbar Spine regions. "
         "These imbalances could predispose injury in the near future."),
        ("How to improve?",
         "Talk to a physiotherapist.\n"
         "- Stretching exercises\n"
         "- Increase muscle in weaker regions\n"
         "- Correct your posture\n"
         "- Perform daily chores with weaker side\n"
         "- Reduce overall body fat"),
    ]
    panel_w = (DATA_W - 2 * 3 * mm) / 3
    panel_h = min(y - _footer_top(), 42 * mm)

    for i, (title, body) in enumerate(panels):
        px = data_x + i * (panel_w + 3 * mm)
        border = PINK if i == 2 else MGRAY
        bg_col = LPINK if i == 2 else LGRAY
        _draw_text_box(c, px, _footer_top(), panel_w, panel_h,
                       title, body, bg=bg_col, border_col=border,
                       title_col=PINK if i == 2 else DARK,
                       body_size=6.5)

    _footer(c)


# ── Page 5: Android-Gynoid Ratio ───────────────────────────────────────────────

def _page5(c, data):
    comp = data.get('composition') or {}

    _header(c, "Android-Gynoid Ratio")

    android_pct = comp.get('android_fat_pct') or 0
    gynoid_pct  = comp.get('gynoid_fat_pct')  or 0
    ag_ratio    = comp.get('ag_ratio') or 0

    y = _content_top()

    PANEL_H = 42 * mm
    LEFT_W  = 48 * mm
    EXPL_W  = (CONTENT_W - LEFT_W - 4 * mm) / 2

    if ag_ratio < 1.0:    ag_col, ag_label = CYAN,  "Normal — Below 1.0"
    elif ag_ratio <= 1.2: ag_col, ag_label = AMBER, "Elevated — 1.0–1.2"
    else:                 ag_col, ag_label = PINK,  "High — Above 1.2"

    c.setFillColor(DARK)
    c.roundRect(MARGIN, y - PANEL_H, LEFT_W, PANEL_H, 3, fill=1, stroke=0)
    c.setFillColor(CYAN)
    c.setFont('Helvetica-Bold', 7)
    c.drawCentredString(MARGIN + LEFT_W / 2, y - 8 * mm, "YOUR A/G RATIO")
    c.setFillColor(ag_col)
    c.setFont('Helvetica-Bold', 28)
    c.drawCentredString(MARGIN + LEFT_W / 2, y - 22 * mm, f"{ag_ratio:.2f}")
    c.setFillColor(white)
    c.setFont('Helvetica', 6.5)
    c.drawCentredString(MARGIN + LEFT_W / 2, y - 31 * mm, ag_label)
    c.setFont('Helvetica-Oblique', 5.5)
    c.drawCentredString(MARGIN + LEFT_W / 2, y - 37 * mm, "Also known as Waist to Hip Ratio")

    ex1_x = MARGIN + LEFT_W + 2 * mm
    ex2_x = ex1_x + EXPL_W + 2 * mm
    _draw_text_box(c, ex1_x, y - PANEL_H, EXPL_W, PANEL_H,
                   "What is A/G Ratio?",
                   "The Android-Gynoid Ratio is the ratio of fat percentage "
                   "in your android (waist) region to your gynoid (hip) region. "
                   "It is also known as the Waist-to-Hip Ratio. "
                   "An A/G ratio below 1.0 is generally associated with "
                   "a pear or hourglass body shape.")
    _draw_text_box(c, ex2_x, y - PANEL_H, EXPL_W, PANEL_H,
                   "What is its significance?",
                   "The A/G ratio is directly correlated to visceral fat. "
                   "Ideally your Android region should carry less fat than "
                   "your Gynoid region (ratio < 1.0). "
                   "A ratio above 1.0 is associated with apple/round body "
                   "shapes and increased metabolic risk.")

    y -= PANEL_H + 10 * mm

    c.setFillColor(DARK)
    c.setFont('Helvetica-Bold', 8.5)
    c.drawString(MARGIN, y, "BODY FAT DISTRIBUTION")
    y -= 9 * mm

    CBAR_H = 18 * mm
    SCALE  = 100.0

    _zones = [(0, 35, HexColor('#C8E6C9')), (35, 50, HexColor('#FFF9C4')),
              (50, 100, HexColor('#FFCDD2'))]

    bar_y = y - CBAR_H

    c.setFillColor(HexColor('#E0E0E0'))
    c.rect(MARGIN, bar_y, CONTENT_W, CBAR_H, fill=1, stroke=0)
    for z_lo, z_hi, z_col in _zones:
        zx = MARGIN + (z_lo / SCALE) * CONTENT_W
        zw = ((z_hi - z_lo) / SCALE) * CONTENT_W
        c.setFillColor(z_col)
        c.rect(zx, bar_y, zw, CBAR_H, fill=1, stroke=0)
    c.setStrokeColor(MGRAY)
    c.setLineWidth(0.5)
    c.rect(MARGIN, bar_y, CONTENT_W, CBAR_H, fill=0, stroke=1)

    android_x = MARGIN + (min(android_pct, SCALE) / SCALE) * CONTENT_W
    c.setFillColor(PINK)
    path = c.beginPath()
    path.moveTo(android_x - 5, bar_y + CBAR_H + 2)
    path.lineTo(android_x + 5, bar_y + CBAR_H + 2)
    path.lineTo(android_x,     bar_y + CBAR_H - 4)
    path.close()
    c.drawPath(path, fill=1, stroke=0)

    gynoid_x = MARGIN + (min(gynoid_pct, SCALE) / SCALE) * CONTENT_W
    c.setFillColor(CYAN)
    path = c.beginPath()
    path.moveTo(gynoid_x - 5, bar_y - 2)
    path.lineTo(gynoid_x + 5, bar_y - 2)
    path.lineTo(gynoid_x,     bar_y + 4)
    path.close()
    c.drawPath(path, fill=1, stroke=0)

    c.setFont('Helvetica-Bold', 7.5)
    c.setFillColor(PINK)
    c.drawCentredString(android_x, bar_y + CBAR_H + 6 * mm, f"Android: {android_pct:.1f}%")
    c.setFillColor(CYAN)
    c.drawCentredString(gynoid_x,  bar_y - 9 * mm,           f"Gynoid: {gynoid_pct:.1f}%")

    c.setStrokeColor(MGRAY)
    c.setFillColor(DGRAY)
    c.setFont('Helvetica', 6)
    c.setLineWidth(0.4)
    for tick in [0, 25, 50, 75, 100]:
        tx = MARGIN + (tick / SCALE) * CONTENT_W
        c.line(tx, bar_y - 1 * mm, tx, bar_y)
        c.drawCentredString(tx, bar_y - 4 * mm, f"{tick}%")

    legend_y = bar_y - 14 * mm
    c.setFillColor(PINK)
    c.rect(MARGIN, legend_y - 2 * mm, 8 * mm, 3.5 * mm, fill=1, stroke=0)
    c.setFillColor(DARK)
    c.setFont('Helvetica', 7)
    c.drawString(MARGIN + 10 * mm, legend_y - 0.5 * mm, "Android fat %")

    c.setFillColor(CYAN)
    c.rect(MARGIN + 55 * mm, legend_y - 2 * mm, 8 * mm, 3.5 * mm, fill=1, stroke=0)
    c.setFillColor(DARK)
    c.drawString(MARGIN + 65 * mm, legend_y - 0.5 * mm, "Gynoid fat %")

    y = legend_y - 8 * mm

    c.setFillColor(DARK)
    c.setFont('Helvetica-Bold', 8.5)
    c.drawString(MARGIN, y, "A/G RATIO REFERENCE")
    y -= 4 * mm

    ref_rows = [
        ["A/G Ratio",                  "Body Shape",        "Risk Level", "Action"],
        ["< 0.8 (F) / < 0.9 (M)",      "Pear / Hourglass",  "Low",        "Maintain"],
        ["0.8–1.0 (F) / 0.9–1.0 (M)", "Moderate",          "Moderate",   "Lifestyle review"],
        ["> 1.0",                       "Apple / Round",     "High",       "Medical review advised"],
    ]
    col_ws = [CONTENT_W * f for f in [0.30, 0.28, 0.20, 0.22]]
    tstyle = TableStyle([
        ('BACKGROUND',    (0, 0), (-1, 0), DARK),
        ('TEXTCOLOR',     (0, 0), (-1, 0), white),
        ('FONTNAME',      (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE',      (0, 0), (-1, -1), 7.5),
        ('ALIGN',         (1, 0), (-1, -1), 'CENTER'),
        ('ALIGN',         (0, 0), (0, -1),  'LEFT'),
        ('ROWBACKGROUNDS',(0, 1), (-1, -1), [white, LGRAY]),
        ('GRID',          (0, 0), (-1, -1), 0.3, MGRAY),
        ('TOPPADDING',    (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING',   (0, 0), (-1, -1), 5),
    ])
    for ri, row in enumerate(ref_rows[1:], 1):
        if ('> 1.0' in row[0] and ag_ratio > 1.0) or \
           ('0.8' in row[0] and 0.8 <= ag_ratio <= 1.0) or \
           ('< 0.8' in row[0] and ag_ratio < 0.8):
            tstyle.add('BACKGROUND', (0, ri), (-1, ri), LPINK)
            tstyle.add('FONTNAME',   (0, ri), (-1, ri), 'Helvetica-Bold')

    tbl = Table(ref_rows, colWidths=col_ws)
    tbl.setStyle(tstyle)
    _, th = tbl.wrapOn(c, CONTENT_W, 200)
    tbl.drawOn(c, MARGIN, y - th)
    y -= th + 10 * mm

    NOTE_H = 18 * mm
    c.setFillColor(LGRAY)
    c.roundRect(MARGIN, y - NOTE_H, CONTENT_W, NOTE_H, 2, fill=1, stroke=0)
    c.setFillColor(TEAL)
    c.setFont('Helvetica-Bold', 7.5)
    c.drawString(MARGIN + 3 * mm, y - 5 * mm, "CLINICAL NOTE")
    c.setFillColor(DGRAY)
    c.setFont('Helvetica', 7)
    note = ("The A/G ratio is correlated with visceral fat and cardiovascular risk. "
            "Values above 1.0 warrant further metabolic evaluation. "
            "Consult your physician for a comprehensive assessment.")
    note_lines = _wrap(note, 'Helvetica', 7, CONTENT_W - 8 * mm)
    note_y = y - 11 * mm
    for line in note_lines[:2]:
        c.drawString(MARGIN + 3 * mm, note_y, line)
        note_y -= 9

    _footer(c)


# ── Page 6: Bone Health ────────────────────────────────────────────────────────

def _page6(c, data):
    bone    = data.get('bone') or {}
    patient = data.get('patient') or {}
    images  = data.get('scan_images') or {}
    regions = bone.get('regions', {})

    _header(c, "Bone Health & Density")

    y = _content_top()

    c.setFillColor(DARK)
    c.setFont('Helvetica-Bold', 12)
    c.drawString(MARGIN, y, "BONE")
    c.setFillColor(MGRAY)
    c.setFont('Helvetica', 12)
    c.drawString(MARGIN + 22 * mm, y, "HEALTH")
    y -= 9 * mm

    IMG_W  = CONTENT_W * 0.33
    DATA_W = CONTENT_W - IMG_W - 4 * mm
    img_x  = MARGIN + DATA_W + 4 * mm

    bone_img = images.get('body_silhouette')
    if bone_img:
        bone_colored = colorize_dexa_silhouette(bone_img, mode='bone')
        _draw_image_scaled(c, bone_colored, img_x, _footer_top() + 6,
                           IMG_W, y - _footer_top() - 6)
        c.setFillColor(MGRAY)
        c.setFont('Helvetica-Oblique', 5.5)
        c.drawCentredString(img_x + IMG_W / 2, _footer_top() + 2, "Bone Density Reference")

    # BMD data table
    ordered = [r for r in BONE_ORDER if r in regions]

    header_row = ['REGION', 'BMD\n(G/CM²)', 'T-SCORE\nYOUNG ADULT', 'Z-SCORE\nAGE MATCHED']
    rows = [header_row]
    for region in ordered:
        rv  = regions.get(region, {})
        bmd = rv.get('bmd')
        T   = rv.get('T')
        Z   = rv.get('Z')
        rows.append([
            region.upper(),
            f"{bmd:.3f}" if bmd is not None else '—',
            f"{T:+.1f}"  if T  is not None else '–',
            f"{Z:+.1f}"  if Z  is not None else '–',
        ])

    col_ws = [DATA_W * f for f in [0.28, 0.24, 0.26, 0.22]]
    tstyle = TableStyle([
        ('BACKGROUND',    (0, 0), (-1, 0), DARK),
        ('TEXTCOLOR',     (0, 0), (-1, 0), white),
        ('FONTNAME',      (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE',      (0, 0), (-1, -1), 7.5),
        ('ALIGN',         (1, 0), (-1, -1), 'CENTER'),
        ('ALIGN',         (0, 0), (0, -1),  'LEFT'),
        ('ROWBACKGROUNDS',(0, 1), (-1, -1), [white, LGRAY]),
        ('GRID',          (0, 0), (-1, -1), 0.3, MGRAY),
        ('TOPPADDING',    (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING',   (0, 0), (-1, -1), 4),
    ])
    if ordered:
        tstyle.add('BACKGROUND', (0, len(ordered)), (-1, len(ordered)), HexColor('#E3F2FD'))
        tstyle.add('FONTNAME',   (0, len(ordered)), (-1, len(ordered)), 'Helvetica-Bold')
    for i, region in enumerate(ordered, 1):
        T = regions.get(region, {}).get('T')
        if T is not None:
            _, fg, bg = classify(T)
            tstyle.add('BACKGROUND', (2, i), (2, i), bg)
            tstyle.add('TEXTCOLOR',  (2, i), (2, i), fg)
            tstyle.add('FONTNAME',   (2, i), (2, i), 'Helvetica-Bold')

    tbl = Table(rows, colWidths=col_ws)
    tbl.setStyle(tstyle)
    _, th = tbl.wrapOn(c, DATA_W, 400)
    tbl.drawOn(c, MARGIN, y - th)
    y -= th + 9 * mm

    # ── T-score visual bars (one per region) ─────────────────────────────────
    c.setFillColor(DARK)
    c.setFont('Helvetica-Bold', 8.5)
    c.drawString(MARGIN, y, "T-SCORE  BY  REGION")
    c.setFillColor(DGRAY)
    c.setFont('Helvetica', 7)
    c.drawString(MARGIN + 40 * mm, y,
                 "  ←  scale: -4 (severe) to +4 (excellent)")
    y -= 5 * mm

    T_SCALE_LO = -4.0
    T_SCALE_HI = +4.0
    T_SCALE_W  = DATA_W
    BAR_H      = 5 * mm
    BAR_GAP    = 2.5 * mm
    LABEL_W    = 20 * mm

    def _t_frac(t):
        return max(0.0, min(1.0, (t - T_SCALE_LO) / (T_SCALE_HI - T_SCALE_LO)))

    zero_x = MARGIN + LABEL_W + _t_frac(0) * (T_SCALE_W - LABEL_W)

    for region in ordered:
        rv = regions.get(region, {})
        T  = rv.get('T')
        if T is None:
            continue

        bar_x = MARGIN + LABEL_W
        bar_w = T_SCALE_W - LABEL_W

        # Background zones
        zones = [
            (T_SCALE_LO, -2.5, LRED),
            (-2.5,       -1.0, LAMBER),
            (-1.0,        T_SCALE_HI, LGREEN),
        ]
        for z_lo, z_hi, z_col in zones:
            zx  = bar_x + _t_frac(z_lo) * bar_w
            zw  = (_t_frac(z_hi) - _t_frac(z_lo)) * bar_w
            c.setFillColor(z_col)
            c.rect(zx, y - BAR_H, zw, BAR_H, fill=1, stroke=0)

        # Marker fill from 0 to T
        frac_zero = _t_frac(0)
        frac_T    = _t_frac(T)
        fill_col  = (LGREEN if T >= -1.0 else (LAMBER if T >= -2.5 else RED))
        if T >= 0:
            fill_x = bar_x + frac_zero * bar_w
            fill_w = (frac_T - frac_zero) * bar_w
            c.setFillColor(TEAL)
        else:
            fill_x = bar_x + frac_T * bar_w
            fill_w = (frac_zero - frac_T) * bar_w
            c.setFillColor(RED if T < -2.5 else AMBER)
        c.rect(fill_x, y - BAR_H + 1, fill_w, BAR_H - 2, fill=1, stroke=0)

        # Border
        c.setStrokeColor(MGRAY)
        c.setLineWidth(0.3)
        c.rect(bar_x, y - BAR_H, bar_w, BAR_H, fill=0, stroke=1)

        # Zero tick
        c.setStrokeColor(DARK)
        c.setLineWidth(0.8)
        c.line(zero_x, y - BAR_H - 1, zero_x, y + 1)

        # Region label
        c.setFillColor(DARK)
        c.setFont('Helvetica-Bold', 7)
        c.drawRightString(bar_x - 2, y - BAR_H + 2, region)

        # T-value label
        t_x = bar_x + _t_frac(T) * bar_w
        c.setFillColor(DARK)
        c.setFont('Helvetica-Bold', 7)
        label_offset = 5 if T >= 0 else -5
        c.drawCentredString(t_x + label_offset, y - BAR_H / 2 - 2.5, f"{T:+.1f}")

        y -= BAR_H + BAR_GAP

    # Scale axis
    y -= 2 * mm
    c.setStrokeColor(MGRAY)
    c.setLineWidth(0.6)
    ax_x = MARGIN + LABEL_W
    ax_w = T_SCALE_W - LABEL_W
    c.line(ax_x, y, ax_x + ax_w, y)
    c.setFillColor(DGRAY)
    c.setFont('Helvetica', 6)
    for tick_v, lbl in [(-4, '-4'), (-2.5, '-2.5\nOsteoporosis'),
                         (-1, '-1\nOsteopenia'), (0, '0'), (4, '+4')]:
        tx = ax_x + _t_frac(tick_v) * ax_w
        c.line(tx, y, tx, y - 1.5 * mm)
        for di, tl in enumerate(lbl.split('\n')):
            c.drawCentredString(tx, y - 4 * mm - di * 7, tl)
    y -= 14 * mm

    # ── Three info boxes ──────────────────────────────────────────────────────
    box_w = (DATA_W - 2 * 3 * mm) / 3
    box_h = y - _footer_top()

    infos = [
        ("What is T-Score and Z-Score?",
         "Young Adult T-Score shows how much your bone mass differs from "
         "a healthy young adult of your gender.\n\n"
         "Age Matched Z-Score shows how your bone mass compares to an "
         "average person of your age group."),
        ("When should I be concerned?",
         "Osteoporosis: T-score ≤ -2.5. Bones become brittle and fracture "
         "risk is high. Consult a doctor immediately.\n\n"
         "Osteopenia: T-score -1.0 to -2.5 — bones are weaker than normal "
         "but not yet osteoporotic."),
        ("How to improve bone density?",
         "- Sufficient Calcium and Vitamin D\n"
         "- Weight-bearing exercise\n"
         "- Avoid smoking and excessive alcohol\n"
         "- Resistance training\n"
         "- Consult physician if T-score < -1.0"),
    ]
    for i, (title, body) in enumerate(infos):
        bx = MARGIN + i * (box_w + 3 * mm)
        _draw_text_box(c, bx, _footer_top(), box_w, box_h, title, body)

    _footer(c)


# ── Page 7: Clinical Recommendations ──────────────────────────────────────────

def _page7(c, data):
    patient = data.get('patient') or {}
    comp    = data.get('composition') or {}
    bone    = data.get('bone') or {}
    total_T = (bone.get('regions', {}).get('Total') or {}).get('T')
    label, _, _ = classify(total_T)
    fat_pct     = comp.get('fat_pct') or 0
    gender      = patient.get('gender', 'Female')
    lean_g      = comp.get('lean_g') or 0
    lean_kg     = lean_g / 1000
    rmr         = int(370 + 21.6 * lean_kg) if lean_kg > 0 else 0
    _, cat_name = _fat_category(fat_pct, gender)

    _header(c, "Clinical Summary & Recommendations")

    y = _content_top()

    # Clinical impression strip
    STRIP_H = 22 * mm
    c.setFillColor(LGRAY)
    c.roundRect(MARGIN, y - STRIP_H, CONTENT_W, STRIP_H, 2, fill=1, stroke=0)
    c.setFillColor(TEAL)
    c.setFont('Helvetica-Bold', 8.5)
    c.drawString(MARGIN + 3 * mm, y - 6 * mm, "CLINICAL IMPRESSION")
    c.setFillColor(DARK)
    c.setFont('Helvetica', 7.5)
    impression = (f"Body Fat: {fat_pct:.1f}%  —  {cat_name}.   "
                  f"Bone Health: {label}  "
                  f"(Total Body T = {f'{total_T:+.1f}' if total_T is not None else 'N/A'}).   "
                  f"Resting Metabolic Rate: {rmr:,} kcal/day.")
    c.drawString(MARGIN + 3 * mm, y - 12 * mm, impression)
    c.setFont('Helvetica-Oblique', 7)
    c.drawString(MARGIN + 3 * mm, y - 18 * mm,
                 "These findings should be interpreted in the clinical context by a qualified physician.")
    y -= STRIP_H + 6 * mm

    # 2×3 recommendation cards
    cards = [
        ("Calcium & Vitamin D",
         "1000–1200 mg Calcium daily (diet + supplement).\n"
         "1000–2000 IU Vitamin D3 daily.\n"
         "Monitor 25-OH Vit D levels 6-monthly."),
        ("Weight-Bearing Exercise",
         "150 min/week moderate aerobic activity.\n"
         "2–3 resistance training sessions/week.\n"
         "Weight-bearing exercise builds bone density."),
        ("Diet & Nutrition",
         f"1.2–1.6 g protein per kg body weight daily.\n"
         "Include lean meats, legumes, eggs, dairy.\n"
         "Reduce processed food and added sugar."),
        ("Follow-Up DEXA",
         "Repeat Total Body DEXA in 24 months.\n"
         "Use the same scanner for comparison.\n"
         "Re-assess after any major intervention."),
        ("Maintain Bone Health" if not (total_T is not None and total_T <= -1.0)
         else "Bone Health Action",
         ("Maintain weight-bearing physical activity.\n"
          "Annual review with bone density monitoring.\n"
          "Adequate calcium and Vitamin D essential.")
         if not (total_T is not None and total_T <= -2.5)
         else ("Bisphosphonate therapy: discuss with physician.\n"
               "FRAX 10-year fracture risk assessment advised.\n"
               "Avoid smoking and excessive alcohol.")),
        ("Physician Referral",
         "Share this report with your treating physician.\n"
         "Further investigation may be warranted based\n"
         "on your individual clinical history."),
    ]

    card_w = (CONTENT_W - 5 * mm) / 2
    gap    = 4 * mm
    disc_h = 15 * mm   # space for disclaimer below cards
    card_h = max(32 * mm, (y - _footer_top() - disc_h - 2 * gap) / 3)

    for i, (title, body) in enumerate(cards):
        col = i % 2
        row = i // 2
        cx  = MARGIN + col * (card_w + 5 * mm)
        cy  = y - row * (card_h + gap)

        c.setFillColor(white)
        c.setStrokeColor(TEAL)
        c.setLineWidth(0.5)
        c.roundRect(cx, cy - card_h, card_w, card_h, 2, fill=1, stroke=1)
        c.setFillColor(TEAL)
        c.rect(cx, cy - 7 * mm, card_w, 7 * mm, fill=1, stroke=0)
        c.setFillColor(white)
        c.setFont('Helvetica-Bold', 7.5)
        c.drawString(cx + 3 * mm, cy - 5 * mm, title)

        c.setFillColor(DARK)
        c.setFont('Helvetica', 7)
        inner_w = card_w - 6 * mm
        body_y  = cy - 11 * mm
        for line in _wrap(body, 'Helvetica', 7, inner_w):
            if body_y < cy - card_h + 2 * mm:
                break
            c.drawString(cx + 3 * mm, body_y, line)
            body_y -= 9.5

    disc_y = y - 3 * (card_h + gap) - 5 * mm
    c.setFillColor(MGRAY)
    c.setFont('Helvetica-Oblique', 6.5)
    disc = ("DISCLAIMER: This report is for qualified healthcare professionals only. "
            "Values should be interpreted in clinical context. "
            "Diagnosis and treatment remain the responsibility of the treating physician.")
    for line in _wrap(disc, 'Helvetica-Oblique', 6.5, CONTENT_W):
        c.drawString(MARGIN, disc_y, line)
        disc_y -= 9

    _footer(c)


# ── Entry point ────────────────────────────────────────────────────────────────

def render_totalbody_pdf(report_data: dict, mode: str = 'screen') -> bytes:
    """
    report_data keys:
      patient:     demographics dict
      bone:        parse_totalbody_bone() output
      composition: parse_totalbody_composition() output + 'regions' from MDB
      scan_images: extract_totalbody_images() output

    mode: 'screen' — full digital design (dark panels, logo)
          'print'  — letterhead mode (light backgrounds, no logo, leaves margins)
    """
    global _render_mode, _logo_fetched
    _render_mode  = mode
    _logo_fetched = False   # re-fetch logo for each render (allows mode switch)

    buf = io.BytesIO()
    c   = canvas.Canvas(buf, pagesize=A4, pageCompression=0)
    c.setTitle("SDRC Total Body Composition Report")
    c.setAuthor(config.CLINIC_NAME)

    _page1(c, report_data);      c.showPage()
    _page2(c, report_data);      c.showPage()
    _page3_rmr(c, report_data);  c.showPage()
    _page4(c, report_data);      c.showPage()
    _page5(c, report_data);      c.showPage()
    _page6(c, report_data);      c.showPage()
    _page7(c, report_data);      c.showPage()

    c.save()
    return buf.getvalue()


# ── Local test ─────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import sys, os
    sys.path.insert(0, os.path.dirname(__file__))
    from parse_xps_totalbody import parse_totalbody_bone, parse_totalbody_composition, extract_totalbody_images
    from parse_mdb import MdbParser

    MDB_PATH   = '../../machine-data/data/lunar.mdb'
    BONE_XPS   = '../../machine-data/total-body-xps/Full_body.xps'
    COMP_XPS   = '../../machine-data/total-body-xps/Full_body-1.xps'
    PATIENT_ID = '250821064'

    bone_data = parse_totalbody_bone(BONE_XPS)
    comp_data = parse_totalbody_composition(COMP_XPS)

    parser  = MdbParser(MDB_PATH)
    pat_row = next(
        (p for p in parser._patients.values()
         if p.get('patient_id', '').strip() == PATIENT_ID),
        None,
    )
    if pat_row:
        img_handle = parser.find_totalbody_img_handle(pat_row['pat_handle'])
        if img_handle:
            comp_data['regions'] = parser.get_totalbody_regions(img_handle)

    imgs = extract_totalbody_images(BONE_XPS, COMP_XPS)
    data = {
        'patient':     bone_data['patient'],
        'bone':        bone_data,
        'composition': comp_data,
        'scan_images': imgs,
    }

    screen_pdf = render_totalbody_pdf(data, mode='screen')
    with open('/Users/pav/projects/bmd/totalbody_screen.pdf', 'wb') as f:
        f.write(screen_pdf)
    print('Screen PDF:', len(screen_pdf), 'bytes')

    print_pdf = render_totalbody_pdf(data, mode='print')
    with open('/Users/pav/projects/bmd/totalbody_print.pdf', 'wb') as f:
        f.write(print_pdf)
    print('Print PDF:', len(print_pdf), 'bytes')
