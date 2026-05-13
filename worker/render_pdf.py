"""
5-page clinical BMD / DEXA report renderer using ReportLab.

Input: report_data dict (see build_report_data() in pipeline.py)
Output: bytes (PDF)
"""

import io
import math
from datetime import date, datetime
from typing import Optional

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.colors import HexColor, Color, white, black
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import Table, TableStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics

import config

# ── Dimensions ────────────────────────────────────────────────────────────
W, H = A4          # 595.27 x 841.89 pts
MARGIN = 14 * mm
CONTENT_W = W - 2 * MARGIN

# ── Colour palette ─────────────────────────────────────────────────────────
DARK  = HexColor("#0D1B2A")
DBLUE = HexColor("#1A3550")
TEAL  = HexColor("#0D7377")
LTEAL = HexColor("#E3F4F4")
MGRAY = HexColor("#BBBBB8")
LGRAY = HexColor("#F6F6F6")
DGRAY = HexColor("#555555")
GREEN = HexColor("#166534"); LGRN = HexColor("#DCFCE7")
AMBER = HexColor("#92400E"); LAMB = HexColor("#FEF3C7")
RED   = HexColor("#991B1B"); LRED = HexColor("#FEE2E2")
IVORY = HexColor("#F9F7F4")


def _hex(c: Color) -> str:
    return "#{:02X}{:02X}{:02X}".format(
        int(c.red * 255), int(c.green * 255), int(c.blue * 255)
    )


# ── WHO classification ─────────────────────────────────────────────────────
def classify(T: Optional[float]) -> tuple[str, Color, Color]:
    if T is None:
        return ('Unknown', MGRAY, LGRAY)
    if T >= -1.0:
        return ('Normal', GREEN, LGRN)
    if T >= -2.5:
        return ('Osteopenia', AMBER, LAMB)
    return ('Osteoporosis', RED, LRED)


def worst_T(data: dict) -> tuple[Optional[float], str]:
    """Return (worst_T_score, site_name)."""
    candidates = []
    for site, v in data.get('spine', {}).items():
        if v and v.get('T') is not None:
            candidates.append((v['T'], f'Spine {site}'))
    for site, v in data.get('left_femur', {}).items():
        if v and v.get('T') is not None:
            candidates.append((v['T'], f'Left Femur {site}'))
    for site, v in data.get('right_femur', {}).items():
        if v and v.get('T') is not None:
            candidates.append((v['T'], f'Right Femur {site}'))
    if not candidates:
        return None, ''
    return min(candidates, key=lambda x: x[0])


# ── PIL image → ReportLab ImageReader ────────────────────────────────────
def _pil_to_rl(img: PILImage.Image) -> ImageReader:
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return ImageReader(buf)


# ── Common page chrome ─────────────────────────────────────────────────────
def _page_chrome(c: canvas.Canvas, page_num: int, section_title: str, patient: dict):
    # Header bar
    c.setFillColor(DARK)
    c.rect(0, H - 13 * mm, W, 13 * mm, fill=1, stroke=0)
    c.setFillColor(TEAL)
    c.rect(0, H - 13 * mm - 1, W, 1.5, fill=1, stroke=0)

    c.setFillColor(white)
    c.setFont('Helvetica-Bold', 8)
    c.drawString(MARGIN, H - 9 * mm, "BONE MINERAL DENSITY REPORT")
    c.setFont('Helvetica', 8)
    name = f"{patient.get('title','')} {patient.get('name','')}".strip()
    c.drawRightString(W - MARGIN, H - 9 * mm, name)

    # Section title strip
    c.setFillColor(TEAL)
    c.rect(0, H - 22 * mm, W, 7 * mm, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont('Helvetica-Bold', 9)
    c.drawString(MARGIN, H - 19 * mm, section_title.upper())

    # Footer
    c.setFillColor(LGRAY)
    c.rect(0, 0, W, 11 * mm, fill=1, stroke=0)
    c.setFillColor(MGRAY)
    c.rect(0, 11 * mm, W, 0.5, fill=1, stroke=0)
    c.setFillColor(DGRAY)
    c.setFont('Helvetica', 7)
    footer_left = f"{config.CLINIC_NAME}  •  {config.CLINIC_ADDRESS}"
    c.drawString(MARGIN, 7 * mm, footer_left)
    c.drawRightString(W - MARGIN, 7 * mm,
                      f"{config.SCANNER_ID}  •  {config.SOFTWARE}  •  Page {page_num}")


# ── T-score scale bar ──────────────────────────────────────────────────────
def _draw_tscore_bar(c: canvas.Canvas, x: float, y: float, width: float,
                     t_value: Optional[float], label: str = ''):
    """Horizontal T-score scale from -4 to +3."""
    T_MIN, T_MAX = -4.0, 3.0
    height = 8 * mm
    bar_h  = 4 * mm

    # Colour bands
    bands = [
        (T_MIN, -2.5, RED),
        (-2.5,  -1.0, AMBER),
        (-1.0,   T_MAX, GREEN),
    ]
    for t0, t1, col in bands:
        bx = x + (t0 - T_MIN) / (T_MAX - T_MIN) * width
        bw = (t1 - t0) / (T_MAX - T_MIN) * width
        c.setFillColor(col)
        c.rect(bx, y + height - bar_h, bw, bar_h, fill=1, stroke=0)

    # Tick marks and labels
    c.setFont('Helvetica', 6)
    c.setFillColor(DGRAY)
    for tv in range(int(T_MIN), int(T_MAX) + 1):
        tx = x + (tv - T_MIN) / (T_MAX - T_MIN) * width
        c.setStrokeColor(white)
        c.line(tx, y + height - bar_h, tx, y + height - bar_h - 2)
        c.drawCentredString(tx, y + height - bar_h - 5, str(tv))

    # Marker for current T-score
    if t_value is not None:
        t_clamped = max(T_MIN, min(T_MAX, t_value))
        mx = x + (t_clamped - T_MIN) / (T_MAX - T_MIN) * width
        c.setFillColor(DARK)
        c.setStrokeColor(white)
        c.setLineWidth(0.5)
        # Triangle marker
        p = c.beginPath()
        p.moveTo(mx, y + height)
        p.lineTo(mx - 3, y + height - bar_h + 1)
        p.lineTo(mx + 3, y + height - bar_h + 1)
        p.close()
        c.drawPath(p, fill=1, stroke=1)
        c.setFillColor(DARK)
        c.setFont('Helvetica-Bold', 7)
        c.drawCentredString(mx, y + height + 2, f"T={t_value:.1f}")

    if label:
        c.setFont('Helvetica', 7)
        c.setFillColor(DGRAY)
        c.drawString(x, y + 1, label)


# ── Classification badge ───────────────────────────────────────────────────
def _badge(c: canvas.Canvas, x: float, y: float, t_value: Optional[float],
           w: float = 22 * mm, h: float = 5 * mm):
    label, fg, bg = classify(t_value)
    c.setFillColor(bg)
    c.roundRect(x, y, w, h, 2, fill=1, stroke=0)
    c.setFillColor(fg)
    c.setFont('Helvetica-Bold', 7)
    c.drawCentredString(x + w / 2, y + 1.5 * mm, label)


# ── Demographic strip ──────────────────────────────────────────────────────
def _draw_demo_strip(c: canvas.Canvas, y: float, patient: dict):
    c.setFillColor(LTEAL)
    c.rect(MARGIN, y, CONTENT_W, 18 * mm, fill=1, stroke=0)
    c.setFillColor(TEAL)
    c.rect(MARGIN, y + 18 * mm - 0.5, CONTENT_W, 0.5, fill=1, stroke=0)
    c.rect(MARGIN, y, CONTENT_W, 0.5, fill=1, stroke=0)

    dob = patient.get('dob', '')
    age = patient.get('age', '')
    if isinstance(dob, date):
        dob = dob.strftime('%d-%m-%Y')

    fields = [
        ("Patient",     f"{patient.get('title','')} {patient.get('name','')}".strip()),
        ("PID",         patient.get('pid') or patient.get('patient_id', '')),
        ("DOB / Age",   f"{dob}  ({age} yrs)" if age else str(dob)),
        ("Sex",         patient.get('gender', '')),
        ("Ht / Wt",     f"{patient.get('height_cm','')} cm  /  {patient.get('weight_kg','')} kg"),
        ("BMI",         f"{patient.get('bmi','')} kg/m²" if patient.get('bmi') else ''),
        ("Physician",   patient.get('physician', '')),
        ("Scan Date",   f"{patient.get('scan_date','')}  {patient.get('scan_time','')}".strip()),
    ]

    cols = 4
    col_w = CONTENT_W / cols
    for i, (label, value) in enumerate(fields):
        col = i % cols
        row = i // cols
        fx = MARGIN + col * col_w + 3 * mm
        fy = y + 14 * mm - row * 8 * mm

        c.setFont('Helvetica-Bold', 6.5)
        c.setFillColor(TEAL)
        c.drawString(fx, fy, label.upper() + ':')

        c.setFont('Helvetica', 8)
        c.setFillColor(DARK)
        c.drawString(fx, fy - 4, str(value))


# ── BMD table ──────────────────────────────────────────────────────────────
def _bmd_table(c: canvas.Canvas, x: float, y: float, width: float,
               sites: list[str], data: dict, side: Optional[str] = None,
               show_bmc_area: bool = True) -> float:
    """
    Draw a BMD results table. Returns the bottom y of the table.
    """
    header = ['Region', 'BMD g/cm²', 'T-Score', 'Z-Score', '%YA']
    if show_bmc_area:
        header += ['BMC (g)', 'Area cm²']

    rows = [header]
    for site in sites:
        v = data.get(site)
        if not v:
            v = {}
        row = [
            site,
            f"{v.get('bmd'):.3f}" if v.get('bmd') is not None else '—',
            f"{v.get('T'):+.1f}"  if v.get('T')   is not None else '—',
            f"{v.get('Z'):+.1f}"  if v.get('Z')   is not None else '—',
            f"{v.get('pYA'):.1f}" if v.get('pYA') is not None else '—',
        ]
        if show_bmc_area:
            row += [
                f"{v.get('bmc'):.2f}"  if v.get('bmc')  is not None else '—',
                f"{v.get('area'):.2f}" if v.get('area') is not None else '—',
            ]
        rows.append(row)

    ncols = len(header)
    col_widths = _col_widths(width, ncols, show_bmc_area)

    style = TableStyle([
        ('BACKGROUND',   (0, 0), (-1, 0),  TEAL),
        ('TEXTCOLOR',    (0, 0), (-1, 0),  white),
        ('FONTNAME',     (0, 0), (-1, 0),  'Helvetica-Bold'),
        ('FONTSIZE',     (0, 0), (-1, -1), 8),
        ('ALIGN',        (1, 0), (-1, -1), 'CENTER'),
        ('ALIGN',        (0, 0), (0, -1),  'LEFT'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, LGRAY]),
        ('GRID',         (0, 0), (-1, -1), 0.3, MGRAY),
        ('TOPPADDING',   (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING',(0, 0), (-1, -1), 3),
        ('LEFTPADDING',  (0, 0), (-1, -1), 4),
    ])

    # Colour T-score cells
    for i, site in enumerate(sites, start=1):
        v = data.get(site, {}) or {}
        t = v.get('T')
        _, fg, bg = classify(t)
        style.add('BACKGROUND', (2, i), (2, i), bg)
        style.add('TEXTCOLOR',  (2, i), (2, i), fg)
        style.add('FONTNAME',   (2, i), (2, i), 'Helvetica-Bold')

    tbl = Table(rows, colWidths=col_widths)
    tbl.setStyle(style)
    tw, th = tbl.wrapOn(c, width, 999)
    tbl.drawOn(c, x, y - th)
    return y - th


def _col_widths(total: float, ncols: int, show_bmc_area: bool) -> list[float]:
    if show_bmc_area and ncols == 7:
        return [total * f for f in [0.16, 0.14, 0.14, 0.14, 0.12, 0.15, 0.15]]
    if ncols == 5:
        return [total * f for f in [0.20, 0.20, 0.20, 0.20, 0.20]]
    # Default equal
    return [total / ncols] * ncols


# ── False-colour legend ────────────────────────────────────────────────────
def _draw_legend(c: canvas.Canvas, x: float, y: float):
    items = [
        (HexColor("#BC4040"), "Soft tissue"),
        (HexColor("#0D9498"), "Lean / muscle"),
        (HexColor("#BCDCE4"), "Bone"),
    ]
    c.setFont('Helvetica', 6.5)
    for i, (col, label) in enumerate(items):
        lx = x + i * 35 * mm
        c.setFillColor(col)
        c.rect(lx, y, 5 * mm, 3 * mm, fill=1, stroke=0)
        c.setFillColor(DGRAY)
        c.drawString(lx + 6 * mm, y + 0.5 * mm, label)


# ── Page 1: Cover & Clinical Summary ──────────────────────────────────────
def _page1(c: canvas.Canvas, data: dict):
    patient = data['patient']
    wt, worst_site = worst_T(data)
    label, fg, bg = classify(wt)

    # ── Big dark header ────────────────────────────────────────────────
    c.setFillColor(DARK)
    c.rect(0, H - 35 * mm, W, 35 * mm, fill=1, stroke=0)
    c.setFillColor(TEAL)
    c.rect(0, H - 35 * mm - 1.5, W, 1.5, fill=1, stroke=0)

    # Clinic name
    c.setFillColor(TEAL)
    c.setFont('Helvetica-Bold', 14)
    c.drawString(MARGIN, H - 14 * mm, config.CLINIC_NAME.upper())
    c.setFillColor(MGRAY)
    c.setFont('Helvetica', 8)
    c.drawString(MARGIN, H - 21 * mm, config.CLINIC_ADDRESS)

    # Report title
    c.setFillColor(white)
    c.setFont('Helvetica-Bold', 11)
    c.drawRightString(W - MARGIN, H - 14 * mm, "DUAL-ENERGY X-RAY ABSORPTIOMETRY")
    c.setFont('Helvetica', 9)
    c.drawRightString(W - MARGIN, H - 21 * mm, "BONE MINERAL DENSITY REPORT")

    c.setFillColor(MGRAY)
    c.setFont('Helvetica', 7)
    c.drawRightString(W - MARGIN, H - 28 * mm,
                      f"Generated: {datetime.now().strftime('%d-%m-%Y %H:%M')}  •  v{config.GENERATOR_VER}")

    # ── Demo strip ──────────────────────────────────────────────────────
    _draw_demo_strip(c, H - 56 * mm, patient)

    # ── Overall result badge ────────────────────────────────────────────
    badge_y = H - 90 * mm
    c.setFillColor(bg)
    c.roundRect(MARGIN, badge_y, 70 * mm, 24 * mm, 4, fill=1, stroke=0)
    c.setFillColor(fg)
    c.setFont('Helvetica-Bold', 15)
    c.drawCentredString(MARGIN + 35 * mm, badge_y + 15 * mm, label.upper())
    c.setFont('Helvetica', 8)
    if wt is not None:
        c.drawCentredString(MARGIN + 35 * mm, badge_y + 8 * mm,
                            f"Worst T-Score: {wt:+.1f}  ({worst_site})")
    else:
        c.drawCentredString(MARGIN + 35 * mm, badge_y + 8 * mm, "No T-score available")

    # WHO legend
    lx = MARGIN + 75 * mm
    ly = badge_y + 4 * mm
    c.setFont('Helvetica-Bold', 8)
    c.setFillColor(DARK)
    c.drawString(lx, badge_y + 20 * mm, "WHO CLASSIFICATION")
    c.setFont('Helvetica', 8)
    who = [
        (GREEN, LGRN, "Normal",       "T-score ≥ -1.0"),
        (AMBER, LAMB, "Osteopenia",   "-2.5 ≤ T-score < -1.0"),
        (RED,   LRED, "Osteoporosis", "T-score < -2.5"),
    ]
    for i, (fg2, bg2, wlabel, wrange) in enumerate(who):
        wy = ly + (2 - i) * 6 * mm
        c.setFillColor(bg2)
        c.rect(lx, wy, 3 * mm, 3 * mm, fill=1, stroke=0)
        c.setFillColor(fg2)
        c.setFont('Helvetica-Bold', 7.5)
        c.drawString(lx + 4 * mm, wy + 0.5 * mm, wlabel)
        c.setFont('Helvetica', 7.5)
        c.setFillColor(DGRAY)
        c.drawString(lx + 28 * mm, wy + 0.5 * mm, wrange)

    # ── T-score scale bars ───────────────────────────────────────────────
    bar_y = badge_y - 25 * mm
    c.setFont('Helvetica-Bold', 8)
    c.setFillColor(DARK)
    c.drawString(MARGIN, bar_y + 17 * mm, "T-SCORE SUMMARY")

    bars = []
    if data.get('spine'):
        bars.append(("AP Spine L1–L4", (data['spine'].get('L1-L4') or {}).get('T')))
    if data.get('left_femur'):
        bars.append(("Left Femur Neck", (data['left_femur'].get('Neck') or {}).get('T')))
    if data.get('right_femur'):
        bars.append(("Right Femur Neck", (data['right_femur'].get('Neck') or {}).get('T')))

    bar_w = CONTENT_W * 0.55
    for i, (blabel, bt) in enumerate(bars):
        by = bar_y + (len(bars) - 1 - i) * 14 * mm
        _draw_tscore_bar(c, MARGIN, by, bar_w, bt, blabel)

    # ── Site summary mini-table ──────────────────────────────────────────
    summary_x = MARGIN + bar_w + 5 * mm
    summary_y = bar_y + 2 * mm
    summary_w = CONTENT_W - bar_w - 5 * mm

    c.setFont('Helvetica-Bold', 8)
    c.setFillColor(DARK)
    c.drawString(summary_x, summary_y + 38 * mm, "ALL-SITES SUMMARY")

    rows2 = [['Site', 'BMD', 'T', 'Status']]
    summary_sites = [
        ('Spine L1-L4', data.get('spine', {}).get('L1-L4')),
        ('L.Femur Neck', data.get('left_femur', {}).get('Neck')),
        ('L.Femur Total', data.get('left_femur', {}).get('Total')),
        ('R.Femur Neck', data.get('right_femur', {}).get('Neck')),
        ('R.Femur Total', data.get('right_femur', {}).get('Total')),
    ]
    for sname, sv in summary_sites:
        if sv:
            slabel, _, _ = classify(sv.get('T'))
            rows2.append([
                sname,
                f"{sv.get('bmd'):.3f}" if sv.get('bmd') is not None else '—',
                f"{sv.get('T'):+.1f}"  if sv.get('T')  is not None else '—',
                slabel,
            ])

    sw = summary_w
    cw = [sw * f for f in [0.35, 0.20, 0.18, 0.27]]
    tstyle = TableStyle([
        ('BACKGROUND',   (0, 0), (-1, 0),  TEAL),
        ('TEXTCOLOR',    (0, 0), (-1, 0),  white),
        ('FONTNAME',     (0, 0), (-1, -1), 'Helvetica'),
        ('FONTNAME',     (0, 0), (-1, 0),  'Helvetica-Bold'),
        ('FONTSIZE',     (0, 0), (-1, -1), 7),
        ('ALIGN',        (1, 0), (-1, -1), 'CENTER'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, LGRAY]),
        ('GRID',         (0, 0), (-1, -1), 0.3, MGRAY),
        ('TOPPADDING',   (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING',(0, 0), (-1, -1), 2),
    ])

    row_idx = 1
    for sname, sv in summary_sites:
        if sv:
            _, fg2, bg2 = classify(sv.get('T'))
            tstyle.add('BACKGROUND', (3, row_idx), (3, row_idx), bg2)
            tstyle.add('TEXTCOLOR',  (3, row_idx), (3, row_idx), fg2)
            tstyle.add('FONTNAME',   (3, row_idx), (3, row_idx), 'Helvetica-Bold')
            row_idx += 1

    tbl2 = Table(rows2, colWidths=cw)
    tbl2.setStyle(tstyle)
    tw2, th2 = tbl2.wrapOn(c, sw, 999)
    tbl2.drawOn(c, summary_x, summary_y + 36 * mm - th2)

    # ── Clinical narrative ───────────────────────────────────────────────
    narr_y = bar_y - 10 * mm
    c.setFillColor(IVORY)
    c.roundRect(MARGIN, narr_y - 24 * mm, CONTENT_W, 28 * mm, 4, fill=1, stroke=0)
    c.setFillColor(TEAL)
    c.setFont('Helvetica-Bold', 8)
    c.drawString(MARGIN + 3 * mm, narr_y, "CLINICAL IMPRESSION")

    narrative = _generate_narrative(data, patient)
    c.setFont('Helvetica', 8)
    c.setFillColor(DARK)
    text_obj = c.beginText(MARGIN + 3 * mm, narr_y - 7 * mm)
    text_obj.setFont('Helvetica', 8)
    text_obj.setFillColor(DARK)
    for line in narrative:
        text_obj.textLine(line)
    c.drawText(text_obj)

    # ── Footer ───────────────────────────────────────────────────────────
    c.setFillColor(LGRAY)
    c.rect(0, 0, W, 11 * mm, fill=1, stroke=0)
    c.setFillColor(MGRAY)
    c.rect(0, 11 * mm, W, 0.5, fill=1, stroke=0)
    c.setFillColor(DGRAY)
    c.setFont('Helvetica', 7)
    c.drawString(MARGIN, 7 * mm,
                 f"{config.CLINIC_NAME}  •  {config.CLINIC_ADDRESS}")
    c.drawRightString(W - MARGIN, 7 * mm,
                      f"{config.SCANNER_ID}  •  {config.SOFTWARE}  •  Page 1")


def _generate_narrative(data: dict, patient: dict) -> list[str]:
    wt, worst_site = worst_T(data)
    label, _, _ = classify(wt)
    name = f"{patient.get('title', '')} {patient.get('name', '')}".strip()
    age  = patient.get('age', '')

    lines = []
    lines.append(f"{name}, {age} yr old {patient.get('gender','').lower()}, underwent DEXA bone density assessment.")

    spine_t  = (data.get('spine', {}).get('L1-L4') or {}).get('T')
    lneck_t  = (data.get('left_femur', {}).get('Neck') or {}).get('T')
    rneck_t  = (data.get('right_femur', {}).get('Neck') or {}).get('T')

    if spine_t is not None:
        sl, _, _ = classify(spine_t)
        lines.append(f"AP Spine (L1–L4): BMD {(data['spine'].get('L1-L4') or {}).get('bmd', 0):.3f} g/cm²,  T={spine_t:+.1f}  →  {sl}.")
    if lneck_t is not None:
        lnl, _, _ = classify(lneck_t)
        lines.append(f"Left Femur Neck: BMD {data['left_femur']['Neck'].get('bmd', 0):.3f} g/cm²,  T={lneck_t:+.1f}  →  {lnl}.")
    if rneck_t is not None:
        rnl, _, _ = classify(rneck_t)
        lines.append(f"Right Femur Neck: BMD {data['right_femur']['Neck'].get('bmd', 0):.3f} g/cm²,  T={rneck_t:+.1f}  →  {rnl}.")
    if wt is not None:
        lines.append(f"Overall assessment: {label} (worst site: {worst_site}, T={wt:+.1f}).")

    return lines


# ── Page 2: AP Spine ──────────────────────────────────────────────────────
def _page2(c: canvas.Canvas, data: dict, page_num: int = 2):
    patient = data['patient']
    _page_chrome(c, page_num, "AP Spine — Lumbar L1 to L4", patient)

    content_top = H - 25 * mm
    img_w = 52 * mm
    img_x = MARGIN
    table_x = MARGIN + img_w + 5 * mm
    table_w = CONTENT_W - img_w - 5 * mm

    # ── Scan image ────────────────────────────────────────────────────
    spine_img = data.get('scan_images', {}).get('spine')
    if spine_img:
        img_h = min(img_w * spine_img.height / spine_img.width, 90 * mm)
        c.drawImage(_pil_to_rl(spine_img), img_x,
                    content_top - img_h, img_w, img_h)
        _draw_legend(c, img_x, content_top - img_h - 8 * mm)
    img_bottom = content_top - 95 * mm

    # ── BMD table ─────────────────────────────────────────────────────
    spine_sites = ['L1', 'L2', 'L3', 'L4', 'L1-L4']
    c.setFont('Helvetica-Bold', 8.5)
    c.setFillColor(DARK)
    c.drawString(table_x, content_top, "DENSITOMETRY RESULTS — AP SPINE")
    table_bottom = _bmd_table(c, table_x, content_top - 4 * mm, table_w,
                               spine_sites, data.get('spine', {}))

    # ── T-score bar for L1–L4 ────────────────────────────────────────
    l14_t = (data.get('spine', {}).get('L1-L4') or {}).get('T')
    bar_y = table_bottom - 20 * mm
    c.setFont('Helvetica-Bold', 8)
    c.setFillColor(DARK)
    c.drawString(table_x, bar_y + 16 * mm, "T-SCORE: L1–L4")
    _draw_tscore_bar(c, table_x, bar_y, table_w, l14_t, "L1–L4 Composite")

    # ── Per-vertebra badges ──────────────────────────────────────────
    badge_y = bar_y - 12 * mm
    c.setFont('Helvetica-Bold', 7.5)
    c.setFillColor(DARK)
    c.drawString(table_x, badge_y + 8 * mm, "CLASSIFICATION PER VERTEBRA")
    for i, site in enumerate(['L1', 'L2', 'L3', 'L4']):
        v = data.get('spine', {}).get(site) or {}
        bx = table_x + i * 25 * mm
        c.setFont('Helvetica', 7)
        c.setFillColor(DGRAY)
        c.drawCentredString(bx + 11 * mm, badge_y + 6 * mm, site)
        _badge(c, bx, badge_y, v.get('T'), w=22 * mm)

    # ── Interpretation bullets ───────────────────────────────────────
    interp_y = badge_y - 4 * mm
    c.setFillColor(TEAL)
    c.setFont('Helvetica-Bold', 8)
    c.drawString(MARGIN, interp_y, "INTERPRETATION")
    c.setFillColor(DARK)
    c.setFont('Helvetica', 8)
    y_cursor = interp_y - 5 * mm
    for site in ['L1', 'L2', 'L3', 'L4']:
        v = data.get('spine', {}).get(site) or {}
        t = v.get('T')
        bmd = v.get('bmd')
        if t is not None:
            slabel, _, _ = classify(t)
            line = f"  {site}: BMD {bmd:.3f} g/cm²,  T={t:+.1f}  ({slabel})"
        else:
            line = f"  {site}: No data"
        c.drawString(MARGIN, y_cursor, line)
        y_cursor -= 4.5 * mm

    # ── Reference note ────────────────────────────────────────────────
    c.setFont('Helvetica-Oblique', 7)
    c.setFillColor(MGRAY)
    c.drawString(MARGIN, 14 * mm,
                 "Reference: USA (Combined NHANES/Lunar) AP Spine v112.  "
                 "Matched for Age, Weight (females 25–100 kg), Ethnic.")


# ── Page 3: Left Femur ────────────────────────────────────────────────────
def _page3(c: canvas.Canvas, data: dict, page_num: int = 3):
    patient = data['patient']
    _page_chrome(c, page_num, "Left Hip / Proximal Femur", patient)

    content_top = H - 25 * mm
    img_w = 52 * mm
    img_x = MARGIN
    table_x = MARGIN + img_w + 5 * mm
    table_w = CONTENT_W - img_w - 5 * mm

    lfem_img = data.get('scan_images', {}).get('left_femur')
    if lfem_img:
        img_h = min(img_w * lfem_img.height / lfem_img.width, 90 * mm)
        c.drawImage(_pil_to_rl(lfem_img), img_x,
                    content_top - img_h, img_w, img_h)
        _draw_legend(c, img_x, content_top - img_h - 8 * mm)

    femur_sites = ['Neck', 'Wards', 'Trochanter', 'Total']
    c.setFont('Helvetica-Bold', 8.5)
    c.setFillColor(DARK)
    c.drawString(table_x, content_top, "DENSITOMETRY RESULTS — LEFT FEMUR")
    table_bottom = _bmd_table(c, table_x, content_top - 4 * mm, table_w,
                               femur_sites, data.get('left_femur', {}))

    # T-score bar for Neck
    neck_t = (data.get('left_femur', {}).get('Neck') or {}).get('T')
    bar_y  = table_bottom - 20 * mm
    c.setFont('Helvetica-Bold', 8)
    c.setFillColor(DARK)
    c.drawString(table_x, bar_y + 16 * mm, "T-SCORE: LEFT FEMUR NECK")
    _draw_tscore_bar(c, table_x, bar_y, table_w, neck_t, "Femur Neck")

    # Badges
    badge_y = bar_y - 12 * mm
    c.setFont('Helvetica-Bold', 7.5)
    c.setFillColor(DARK)
    c.drawString(table_x, badge_y + 8 * mm, "REGIONAL CLASSIFICATION")
    for i, site in enumerate(['Neck', 'Wards', 'Trochanter', 'Total']):
        v = data.get('left_femur', {}).get(site) or {}
        bx = table_x + i * 25 * mm
        c.setFont('Helvetica', 7)
        c.setFillColor(DGRAY)
        c.drawCentredString(bx + 11 * mm, badge_y + 6 * mm, site)
        _badge(c, bx, badge_y, v.get('T'), w=22 * mm)

    # Note about Ward's / Trochanter
    c.setFont('Helvetica-Oblique', 7)
    c.setFillColor(MGRAY)
    c.drawString(MARGIN, 18 * mm,
                 "Ward's Triangle and Trochanter values sourced from MDB database (not printed in XPS).")
    c.drawString(MARGIN, 14 * mm,
                 "Reference: USA (Combined NHANES/Lunar) Femur v112.  Matched for Age, Weight, Ethnic.")


# ── Page 4: Right Femur + Bilateral Comparison ────────────────────────────
def _page4(c: canvas.Canvas, data: dict, page_num: int = 4):
    patient = data['patient']
    _page_chrome(c, page_num, "Right Hip / Proximal Femur  +  Bilateral Comparison", patient)

    content_top = H - 25 * mm
    img_w = 52 * mm
    img_x = MARGIN
    table_x = MARGIN + img_w + 5 * mm
    table_w = CONTENT_W - img_w - 5 * mm

    rfem_img = data.get('scan_images', {}).get('right_femur')
    if rfem_img:
        img_h = min(img_w * rfem_img.height / rfem_img.width, 90 * mm)
        c.drawImage(_pil_to_rl(rfem_img), img_x,
                    content_top - img_h, img_w, img_h)
        _draw_legend(c, img_x, content_top - img_h - 8 * mm)

    rfem_sites = ['Neck', 'Total']
    c.setFont('Helvetica-Bold', 8.5)
    c.setFillColor(DARK)
    c.drawString(table_x, content_top, "DENSITOMETRY RESULTS — RIGHT FEMUR")
    table_bottom_r = _bmd_table(c, table_x, content_top - 4 * mm, table_w,
                                 rfem_sites, data.get('right_femur', {}),
                                 show_bmc_area=False)

    # T-score bar right neck
    rneck_t = (data.get('right_femur', {}).get('Neck') or {}).get('T')
    rbar_y  = table_bottom_r - 20 * mm
    c.setFont('Helvetica-Bold', 8)
    c.setFillColor(DARK)
    c.drawString(table_x, rbar_y + 16 * mm, "T-SCORE: RIGHT FEMUR NECK")
    _draw_tscore_bar(c, table_x, rbar_y, table_w, rneck_t, "Right Neck")

    # ── Bilateral comparison ─────────────────────────────────────────
    if data.get('left_femur') and data.get('right_femur'):
        bilat_y = rbar_y - 15 * mm
        c.setFillColor(TEAL)
        c.setFont('Helvetica-Bold', 8.5)
        c.drawString(MARGIN, bilat_y, "BILATERAL COMPARISON")

        bilat_rows = [['Site', 'Left BMD', 'Left T', 'Right BMD', 'Right T', 'Δ BMD']]
        for site in ['Neck', 'Total']:
            lv = data.get('left_femur', {}).get(site) or {}
            rv = data.get('right_femur', {}).get(site) or {}
            lbmd = lv.get('bmd')
            rbmd = rv.get('bmd')
            delta = round(lbmd - rbmd, 3) if lbmd and rbmd else None
            bilat_rows.append([
                site,
                f"{lbmd:.3f}" if lbmd else '—',
                f"{lv.get('T'):+.1f}" if lv.get('T') is not None else '—',
                f"{rbmd:.3f}" if rbmd else '—',
                f"{rv.get('T'):+.1f}" if rv.get('T') is not None else '—',
                f"{delta:+.3f}" if delta is not None else '—',
            ])

        bcw = [CONTENT_W * f for f in [0.16, 0.17, 0.17, 0.17, 0.17, 0.16]]
        btbl = Table(bilat_rows, colWidths=bcw)
        btbl.setStyle(TableStyle([
            ('BACKGROUND',   (0, 0), (-1, 0),  DBLUE),
            ('TEXTCOLOR',    (0, 0), (-1, 0),  white),
            ('FONTNAME',     (0, 0), (-1, 0),  'Helvetica-Bold'),
            ('FONTSIZE',     (0, 0), (-1, -1), 8),
            ('ALIGN',        (1, 0), (-1, -1), 'CENTER'),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, LGRAY]),
            ('GRID',         (0, 0), (-1, -1), 0.3, MGRAY),
            ('TOPPADDING',   (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING',(0, 0), (-1, -1), 3),
        ]))
        btw, bth = btbl.wrapOn(c, CONTENT_W, 999)
        btbl.drawOn(c, MARGIN, bilat_y - 4 * mm - bth)
        allsites_y = bilat_y - 4 * mm - bth - 12 * mm
    else:
        allsites_y = rbar_y - 15 * mm

    # ── All-sites summary ────────────────────────────────────────────
    c.setFillColor(TEAL)
    c.setFont('Helvetica-Bold', 8.5)
    c.drawString(MARGIN, allsites_y, "ALL SITES SUMMARY")

    all_rows = [['Site', 'Side', 'BMD', 'T-Score', 'Z-Score', 'Status']]
    all_sites = [
        ('L1',         'Spine', data.get('spine', {}).get('L1')),
        ('L2',         'Spine', data.get('spine', {}).get('L2')),
        ('L3',         'Spine', data.get('spine', {}).get('L3')),
        ('L4',         'Spine', data.get('spine', {}).get('L4')),
        ('L1-L4',      'Spine', data.get('spine', {}).get('L1-L4')),
        ('Neck',       'Left',  data.get('left_femur', {}).get('Neck')),
        ('Wards',      'Left',  data.get('left_femur', {}).get('Wards')),
        ('Trochanter', 'Left',  data.get('left_femur', {}).get('Trochanter')),
        ('Total',      'Left',  data.get('left_femur', {}).get('Total')),
        ('Neck',       'Right', data.get('right_femur', {}).get('Neck')),
        ('Total',      'Right', data.get('right_femur', {}).get('Total')),
    ]
    for sname, sside, sv in all_sites:
        if sv:
            slabel, _, _ = classify(sv.get('T'))
            all_rows.append([
                sname, sside,
                f"{sv.get('bmd'):.3f}" if sv.get('bmd') is not None else '—',
                f"{sv.get('T'):+.1f}"  if sv.get('T')  is not None else '—',
                f"{sv.get('Z'):+.1f}"  if sv.get('Z')  is not None else '—',
                slabel,
            ])

    acw = [CONTENT_W * f for f in [0.16, 0.12, 0.15, 0.15, 0.15, 0.27]]
    atbl = Table(all_rows, colWidths=acw)
    astyle = TableStyle([
        ('BACKGROUND',   (0, 0), (-1, 0),  TEAL),
        ('TEXTCOLOR',    (0, 0), (-1, 0),  white),
        ('FONTNAME',     (0, 0), (-1, 0),  'Helvetica-Bold'),
        ('FONTSIZE',     (0, 0), (-1, -1), 7.5),
        ('ALIGN',        (2, 0), (-1, -1), 'CENTER'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, LGRAY]),
        ('GRID',         (0, 0), (-1, -1), 0.3, MGRAY),
        ('TOPPADDING',   (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING',(0, 0), (-1, -1), 2),
    ])
    row_idx2 = 1
    for sname, sside, sv in all_sites:
        if sv:
            _, fg2, bg2 = classify(sv.get('T'))
            astyle.add('BACKGROUND', (5, row_idx2), (5, row_idx2), bg2)
            astyle.add('TEXTCOLOR',  (5, row_idx2), (5, row_idx2), fg2)
            astyle.add('FONTNAME',   (5, row_idx2), (5, row_idx2), 'Helvetica-Bold')
            row_idx2 += 1
    atbl.setStyle(astyle)
    atw, ath = atbl.wrapOn(c, CONTENT_W, 999)
    atbl.drawOn(c, MARGIN, allsites_y - 4 * mm - ath)


# ── Page 5: Recommendations ───────────────────────────────────────────────
def _page5(c: canvas.Canvas, data: dict, page_num: int = 5):
    patient = data['patient']
    _page_chrome(c, page_num, "Recommendations & Follow-up Plan", patient)

    wt, worst_site = worst_T(data)
    label, _, _ = classify(wt)
    content_top = H - 27 * mm

    # ── Recommendation cards ─────────────────────────────────────────
    cards = [
        ("Calcium & Vitamin D",
         "1000–1200 mg Calcium daily (diet + supplement).\n1000–2000 IU Vitamin D3 daily.\nMonitor 25-OH Vit D levels 6-monthly."),
        ("Weight-Bearing Exercise",
         "30 min weight-bearing activity 5×/week.\nResistance training 2–3×/week.\nBalance exercises to reduce fall risk."),
        ("Falls Prevention",
         "Home hazard assessment recommended.\nAvoid sedative medications if possible.\nReview footwear and vision annually."),
        ("Pharmacotherapy",
         f"{'Bisphosphonate therapy considered (T ≤ −2.5 or FRAX threshold reached).' if wt is not None and wt <= -2.5 else 'Pharmacotherapy not indicated at this stage.'}\nReview with treating physician."),
        ("FRAX Assessment",
         "10-year fracture probability should be calculated\nusing FRAX tool (frax.shef.ac.uk).\nIncorporate clinical risk factors."),
        ("Repeat DEXA Scan",
         f"{'Repeat DEXA in 12–24 months to monitor response to therapy.' if wt is not None and wt <= -2.5 else 'Routine repeat DEXA in 24 months.'}\nUse same scanner for longitudinal comparison."),
    ]

    card_w = (CONTENT_W - 5 * mm) / 2
    card_h = 28 * mm
    gap    = 4 * mm

    for i, (title, body) in enumerate(cards):
        col = i % 2
        row = i // 2
        cx = MARGIN + col * (card_w + 5 * mm)
        cy = content_top - row * (card_h + gap) - card_h

        c.setFillColor(LTEAL)
        c.roundRect(cx, cy, card_w, card_h, 3, fill=1, stroke=0)
        c.setFillColor(TEAL)
        c.rect(cx, cy + card_h - 7 * mm, card_w, 7 * mm, fill=1, stroke=0)
        # Clip title to card
        c.saveState()
        c.clipPath(c.beginPath(), stroke=0, fill=0)
        c.setFillColor(white)
        c.setFont('Helvetica-Bold', 8)
        c.drawString(cx + 3 * mm, cy + card_h - 5 * mm, title)
        c.restoreState()

        c.setFillColor(white)
        c.setFont('Helvetica-Bold', 8)
        c.drawString(cx + 3 * mm, cy + card_h - 5 * mm, title)

        c.setFillColor(DARK)
        c.setFont('Helvetica', 7.5)
        text_y = cy + card_h - 11 * mm
        for line in body.split('\n'):
            c.drawString(cx + 3 * mm, text_y, line)
            text_y -= 4.5 * mm

    # ── Follow-up timeline ───────────────────────────────────────────
    timeline_y = content_top - 3 * (card_h + gap) - 10 * mm
    c.setFillColor(TEAL)
    c.setFont('Helvetica-Bold', 9)
    c.drawString(MARGIN, timeline_y, "FOLLOW-UP PLAN")

    milestones = [
        ("Immediate",     "Physician review, start calcium/Vit D, FRAX calculation"),
        ("1–3 months",    "Confirm pharmacotherapy decision, lifestyle counselling"),
        ("6 months",      "Vit D level recheck, medication compliance review"),
        ("24 months",     "Repeat DEXA scan (same scanner for valid comparison)"),
    ]
    mw = CONTENT_W / 4
    for i, (mtime, mtext) in enumerate(milestones):
        mx = MARGIN + i * mw
        c.setFillColor(DBLUE)
        c.rect(mx, timeline_y - 10 * mm, mw - 2, 6 * mm, fill=1, stroke=0)
        c.setFillColor(white)
        c.setFont('Helvetica-Bold', 7.5)
        c.drawCentredString(mx + (mw - 2) / 2, timeline_y - 7 * mm, mtime)
        c.setFillColor(DARK)
        c.setFont('Helvetica', 7)
        words = mtext.split(', ')
        ty = timeline_y - 12 * mm
        for w in words:
            c.drawCentredString(mx + (mw - 2) / 2, ty, w)
            ty -= 3.5 * mm

    # ── Data provenance ──────────────────────────────────────────────
    prov_y = timeline_y - 26 * mm
    c.setFillColor(LGRAY)
    c.roundRect(MARGIN, prov_y - 14 * mm, CONTENT_W, 18 * mm, 3, fill=1, stroke=0)
    c.setFillColor(TEAL)
    c.setFont('Helvetica-Bold', 8)
    c.drawString(MARGIN + 3 * mm, prov_y, "DATA PROVENANCE")
    c.setFillColor(DGRAY)
    c.setFont('Helvetica', 7.5)
    c.drawString(MARGIN + 3 * mm, prov_y - 5 * mm,
                 "BMD, T-score, Z-score: sourced from XPS file (GE Lunar DPX printed output — authoritative).")
    c.drawString(MARGIN + 3 * mm, prov_y - 9 * mm,
                 "BMC, Area, Ward's Triangle, Trochanter: sourced from MDB database (supplementary).")
    c.drawString(MARGIN + 3 * mm, prov_y - 13 * mm,
                 f"Scanner: {config.SCANNER_ID}  •  Software: {config.SOFTWARE}  •  Report v{config.GENERATOR_VER}")

    # ── Disclaimer ───────────────────────────────────────────────────
    c.setFillColor(MGRAY)
    c.setFont('Helvetica-Oblique', 6.5)
    disclaimer = (
        "DISCLAIMER: This report is intended for qualified healthcare professionals only. "
        "Values should be interpreted in clinical context. "
        "Images are for illustrative purposes and not for primary diagnosis. "
        "Diagnosis and treatment decisions remain the responsibility of the treating physician."
    )
    c.drawString(MARGIN, 14 * mm, disclaimer[:95])
    c.drawString(MARGIN, 10.5 * mm, disclaimer[95:])


# ── Main entry point ──────────────────────────────────────────────────────
def render_pdf(report_data: dict) -> bytes:
    has_spine = bool(report_data.get('spine'))
    has_lfem  = bool(report_data.get('left_femur'))
    has_rfem  = bool(report_data.get('right_femur'))

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle("SDRC BMD Report")
    c.setAuthor(config.CLINIC_NAME)

    pn = 1
    _page1(c, report_data)
    c.showPage(); pn += 1

    if has_spine:
        _page2(c, report_data, page_num=pn)
        c.showPage(); pn += 1

    if has_lfem:
        _page3(c, report_data, page_num=pn)
        c.showPage(); pn += 1

    if has_rfem:
        _page4(c, report_data, page_num=pn)
        c.showPage(); pn += 1

    _page5(c, report_data, page_num=pn)
    c.showPage()

    c.save()
    return buf.getvalue()
