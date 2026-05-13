import type { OsteoReportData, OsteoRegion, OsteoClassification } from './osteo-types'

/* ── Palette (matches bmd-html-template) ─────────────────────────────────── */
const C = {
  teal: '#0D7377', tealLt: '#14a8ae',
  green: '#2E7D32', greenLt: '#4CAF50',
  amber: '#E65100', red: '#B71C1C',
  bone: '#B0BEC5',
}

type Pal = {
  bg: string; card: string; border: string
  text: string; gray: string; grayLt: string
  cardHighlight: string
  statusGood: string; statusWarn: string; statusAlert: string; statusInfo: string
}

const darkPal: Pal = {
  bg: '#0D1B2A', card: '#0f2235', border: '#1a3a55',
  text: '#FFFFFF', gray: '#9E9E9E', grayLt: '#CFD8DC',
  cardHighlight: '#0a1f30',
  statusGood: '#0a2a0a', statusWarn: '#2a1a00', statusAlert: '#2a0a0a', statusInfo: '#0a1a2a',
}

const lightPal: Pal = {
  bg: '#ffffff', card: '#f5f7fa', border: '#d0dce8',
  text: '#1a1a2e', gray: '#6b7280', grayLt: '#374151',
  cardHighlight: '#e8f4fb',
  statusGood: '#e8f5e8', statusWarn: '#fff3e0', statusAlert: '#fce8e8', statusInfo: '#e3f2fd',
}

const css = (P: Pal, lh = false) => lh ? `
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:#fff;font-family:'Inter',sans-serif;color:#1a1a2e;-webkit-print-color-adjust:exact;print-color-adjust:exact}
  .page{width:210mm;min-height:197mm;padding:6mm 15mm;margin:0 auto;background:#fff;page-break-after:always;display:flex;flex-direction:column}
  .page:last-child{page-break-after:auto}
  @page{size:A4;margin:35mm 15mm 51mm 15mm}
  .row{display:flex;gap:14px}.col{display:flex;flex-direction:column}
  .card{background:#f5f7fa;border:1px solid #d0dce8;border-radius:6px;padding:14px}
  .lbl{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.8px;color:#6b7280}
  .sec{font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#0D7377;margin-bottom:10px}
  .tag{display:inline-block;padding:4px 12px;border-radius:3px;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.5px}
  .sdrc-logo{display:none}
` : `
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:${P.bg};font-family:'Inter',sans-serif;color:${P.text};-webkit-print-color-adjust:exact;print-color-adjust:exact}
  .page{width:210mm;height:297mm;padding:10mm 13mm;margin:0 auto;background:${P.bg};page-break-after:always;position:relative;display:flex;flex-direction:column;overflow:hidden}
  .page:last-child{page-break-after:auto}
  @page{size:A4;margin:0}
  .row{display:flex;gap:14px}.col{display:flex;flex-direction:column}
  .card{background:${P.card};border:1px solid ${P.border};border-radius:8px;padding:16px}
  .lbl{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.8px;color:${P.gray}}
  .sec{font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:${C.tealLt};margin-bottom:10px}
  .tag{display:inline-block;padding:4px 12px;border-radius:3px;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.5px}
`

function esc(s: string | number | undefined) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}
function s(style: string) { return `style="${style}"` }

/* ── WHO classification helpers ─────────────────────────────────────────── */
function classColor(cls: OsteoClassification) {
  return cls === 'osteoporosis' ? C.red : cls === 'osteopenia' ? C.amber : C.greenLt
}
function classBg(cls: OsteoClassification, P: Pal) {
  return cls === 'osteoporosis' ? P.statusAlert : cls === 'osteopenia' ? P.statusWarn : P.statusGood
}
function classLabel(cls: OsteoClassification) {
  return cls === 'osteoporosis' ? 'Osteoporosis' : cls === 'osteopenia' ? 'Osteopenia' : 'Normal Bone Density'
}
function classBadge(cls: OsteoClassification) {
  const c = classColor(cls)
  return `<span class="tag" ${s(`color:${c};background:${c}22;border:1px solid ${c}44`)}>${classLabel(cls)}</span>`
}

/* ── T-score bar ─────────────────────────────────────────────────────────── */
function tScoreBar(t: number, P: Pal) {
  const pct = Math.min(Math.max(((t + 4) / 8) * 100, 1), 99)
  return `
  <div ${s('position:relative;margin-bottom:8px')}>
    <div ${s('display:flex;height:22px;border-radius:5px;overflow:hidden')}>
      <div ${s(`width:18.75%;background:${C.red};display:flex;align-items:center;justify-content:center`)}>
        <span ${s('font-size:8px;color:#fff;font-weight:700')}>Osteoporosis</span></div>
      <div ${s(`width:18.75%;background:${C.amber};display:flex;align-items:center;justify-content:center`)}>
        <span ${s('font-size:8px;color:#fff;font-weight:700')}>Osteopenia</span></div>
      <div ${s(`width:62.5%;background:${C.greenLt};display:flex;align-items:center;justify-content:center`)}>
        <span ${s('font-size:8px;color:#fff;font-weight:700')}>Normal</span></div>
    </div>
    <div ${s(`position:absolute;left:${pct}%;top:-5px;width:4px;height:32px;background:${P.text};border-radius:2px;transform:translateX(-50%);box-shadow:0 0 4px rgba(0,0,0,.5)`)}></div>
  </div>
  <div ${s(`display:flex;justify-content:space-between;font-size:9px;color:${P.gray}`)}>
    <span>−4</span><span>−2.5</span><span>−1</span><span>0</span><span>+4</span>
  </div>`
}

/* ── BMD table ───────────────────────────────────────────────────────────── */
function bmdRow(
  site: string, r: OsteoRegion, isTotal: boolean, P: Pal
) {
  const tColor = r.T == null ? P.gray : r.T <= -2.5 ? C.red : r.T <= -1 ? C.amber : C.greenLt
  const zColor = r.Z == null ? P.gray : r.Z <= -2.0 ? C.red : C.greenLt
  const bmdColor = r.bmd > 0.9 ? C.greenLt : r.bmd > 0.7 ? C.amber : C.red
  const tSign = r.T != null && r.T >= 0 ? '+' : ''
  const zSign = r.Z != null && r.Z >= 0 ? '+' : ''
  const rowBg = isTotal ? `background:${P.cardHighlight};font-weight:700` : ''
  return `<tr ${s(rowBg)}>
    <td style="padding:8px 10px;font-size:11px;color:${isTotal ? P.text : P.grayLt};font-weight:${isTotal ? 700 : 500};border-bottom:1px solid ${P.border}">${esc(site)}</td>
    <td style="padding:8px 10px;font-size:11px;font-family:monospace;text-align:right;color:${bmdColor};border-bottom:1px solid ${P.border}">${r.bmd.toFixed(3)}</td>
    <td style="padding:8px 10px;font-size:11px;font-family:monospace;text-align:right;color:${tColor};border-bottom:1px solid ${P.border}">${r.T != null ? tSign + r.T.toFixed(1) : '—'}</td>
    <td style="padding:8px 10px;font-size:11px;font-family:monospace;text-align:right;color:${zColor};border-bottom:1px solid ${P.border}">${r.Z != null ? zSign + r.Z.toFixed(1) : '—'}</td>
    <td style="padding:8px 10px;font-size:10px;text-align:right;color:${P.gray};border-bottom:1px solid ${P.border}">${r.pYA != null ? r.pYA.toFixed(0) + '%' : '—'}</td>
  </tr>`
}

function bmdTable(
  rows: [string, OsteoRegion | undefined, boolean][],
  P: Pal
) {
  return `
  <table style="width:100%;border-collapse:collapse">
    <thead>
      <tr style="border-bottom:2px solid ${P.border}">
        <th style="padding:6px 10px;font-size:10px;font-weight:700;color:${P.gray};text-align:left;text-transform:uppercase;letter-spacing:.5px">Region</th>
        <th style="padding:6px 10px;font-size:10px;font-weight:700;color:${P.gray};text-align:right;text-transform:uppercase;letter-spacing:.5px">BMD g/cm²</th>
        <th style="padding:6px 10px;font-size:10px;font-weight:700;color:${P.gray};text-align:right;text-transform:uppercase;letter-spacing:.5px">T-Score</th>
        <th style="padding:6px 10px;font-size:10px;font-weight:700;color:${P.gray};text-align:right;text-transform:uppercase;letter-spacing:.5px">Z-Score</th>
        <th style="padding:6px 10px;font-size:10px;font-weight:700;color:${P.gray};text-align:right;text-transform:uppercase;letter-spacing:.5px">% Young Adult</th>
      </tr>
    </thead>
    <tbody>
      ${rows.filter(([, r]) => r != null).map(([site, r, total]) => bmdRow(site, r!, total, P)).join('')}
    </tbody>
  </table>
  <div style="font-size:9px;color:${P.gray};margin-top:6px">
    BMD: <span style="color:${C.greenLt}">■</span> &gt;0.9 · <span style="color:${C.amber}">■</span> 0.7–0.9 · <span style="color:${C.red}">■</span> &lt;0.7 g/cm² &nbsp;·&nbsp;
    T-Score: <span style="color:${C.greenLt}">■</span> ≥−1.0 Normal · <span style="color:${C.amber}">■</span> −1 to −2.5 Osteopenia · <span style="color:${C.red}">■</span> ≤−2.5 Osteoporosis
  </div>`
}

/* ── Header ──────────────────────────────────────────────────────────────── */
function header(
  pt: OsteoReportData['patient'], title: string, P: Pal, lh: boolean, pageNum: number, total: number
) {
  const pgTag = `<span ${s(`font-size:10px;font-weight:500;color:${P.gray}`)}>Page ${pageNum} / ${total}</span>`
  const logoRow = lh ? '' : `
    <div ${s(`display:flex;justify-content:space-between;align-items:center;padding-bottom:8px;margin-bottom:8px;border-bottom:1px solid ${P.border}`)}>
      <img src="/sdrc-logo.png" alt="SDRC Diagnostics" class="sdrc-logo" ${s(`height:36px;width:auto;border-radius:4px`)}>
      <div ${s(`text-align:right;font-size:10px;color:${P.gray};line-height:1.7`)}>
        <div ${s(`color:${P.text};font-weight:700;font-size:11px`)}>${esc(pt.name)}</div>
        <div>${esc(pt.gender)} · ${pt.age}y · ${pt.height_cm} cm · ${pt.weight_kg} kg</div>
        <div>ID: ${esc(pt.id)} · Scan: ${esc(pt.scan_date)} ${esc(pt.scan_time)}</div>
      </div>
    </div>`

  const inner = lh
    ? `<div ${s('display:flex;justify-content:space-between;align-items:baseline;margin-bottom:4px')}>
        <div ${s(`font-size:20px;font-weight:800;color:${P.text}`)}>${esc(title)}</div>
        <div ${s('display:flex;align-items:baseline;gap:14px')}>
          <div ${s(`font-size:10px;color:${P.gray}`)}>
            <span ${s(`color:${P.text};font-weight:700`)}>${esc(pt.name)}</span>
            · ID: ${esc(pt.id)} · ${esc(pt.gender)} · ${pt.age}y · Scan ${esc(pt.scan_date)}
          </div>
          ${pgTag}
        </div>
      </div>`
    : `<div ${s('display:flex;justify-content:space-between;align-items:baseline')}>
        <div ${s(`font-size:20px;font-weight:800;color:${P.text}`)}>${esc(title)}</div>
        ${pgTag}
      </div>`

  return `
  <div ${s('margin-bottom:12px;flex-shrink:0')}>
    ${logoRow}
    <div ${s(`border-bottom:2px solid ${C.teal};padding-bottom:6px`)}>${inner}</div>
  </div>`
}

/* ── Scan footnotes ──────────────────────────────────────────────────────── */
function scanFootnotes(lines: string[], P: Pal) {
  return `
  <div ${s(`margin-top:auto;padding-top:8px;border-top:1px solid ${P.border};font-size:8.5px;color:${P.gray};line-height:1.8;flex-shrink:0`)}>
    ${lines.map((l, i) => `<span>${i + 1}. ${l}</span>`).join(' &nbsp;·&nbsp; ')}
  </div>`
}

/* ── Page 1: Spine BMD ───────────────────────────────────────────────────── */
function page1(data: OsteoReportData, P: Pal, lh: boolean, pageNum: number, total: number) {
  const { patient: pt, spine, summary, images } = data
  const spineTotal = spine['L1-L4']
  const spineT = summary.spine_t
  const cls = summary.spine_class

  const spineRows: [string, OsteoRegion | undefined, boolean][] = [
    ['L1',    spine.L1,       false],
    ['L2',    spine.L2,       false],
    ['L3',    spine.L3,       false],
    ['L4',    spine.L4,       false],
    ['L1–L4', spine['L1-L4'], true ],
  ]

  const ageNote = summary.premenopausal
    ? `<div ${s(`font-size:10px;color:${C.amber};margin-top:8px;line-height:1.6;border-top:1px solid ${P.border};padding-top:8px`)}>
        ⚠ Patient is a premenopausal woman (&lt;50 years). WHO T-score criteria are defined for postmenopausal women and men ≥50.
        Z-score is the preferred diagnostic reference in this age group — values ≤−2.0 indicate "below expected range for age."
      </div>` : ''

  return `
<div class="page">
  ${header(pt, 'Spine Bone Density — AP Lumbar', P, lh, pageNum, total)}
  <div class="col" ${s('flex:1;gap:14px;min-height:0')}>
    <div class="card" ${s(`background:${classBg(cls, P)};flex-shrink:0`)}>
      <div class="row" ${s('align-items:flex-end;gap:24px;margin-bottom:14px')}>
        <div ${s('flex:1;display:flex;flex-direction:column')}>
          <div class="lbl">L1–L4 Total BMD</div>
          <div ${s(`font-size:9px;color:${P.gray};margin-top:2px`)}>AP lumbar spine bone mineral density</div>
          <div ${s('margin-top:8px')}>${classBadge(cls)}</div>
          <div ${s('display:flex;align-items:baseline;gap:5px;margin-top:14px')}>
            <span ${s(`font-size:46px;font-weight:800;color:${classColor(cls)};line-height:1`)}>${spineTotal?.bmd.toFixed(3) ?? '—'}</span>
            <span ${s(`font-size:11px;color:${P.gray}`)}>g/cm²</span>
          </div>
        </div>
        ${spineT != null ? `
        <div ${s('display:flex;flex-direction:column')}>
          <div class="lbl">T-Score</div>
          <div ${s(`font-size:9px;color:${P.gray};margin-top:2px`)}>vs peak bone mass (age 30)</div>
          <div ${s('flex:1;min-height:12px')}></div>
          <div ${s(`font-size:38px;font-weight:800;color:${classColor(cls)};line-height:1;margin-top:4px`)}>${spineT >= 0 ? '+' : ''}${spineT.toFixed(1)}</div>
        </div>
        <div ${s('display:flex;flex-direction:column')}>
          <div class="lbl">Z-Score</div>
          <div ${s(`font-size:9px;color:${P.gray};margin-top:2px`)}>vs same age &amp; sex peers</div>
          <div ${s('flex:1;min-height:12px')}></div>
          <div ${s(`font-size:38px;font-weight:800;color:${summary.spine_z != null && summary.spine_z <= -2 ? C.red : C.greenLt};line-height:1;margin-top:4px`)}>${summary.spine_z != null ? (summary.spine_z >= 0 ? '+' : '') + summary.spine_z.toFixed(1) : '—'}</div>
        </div>` : ''}
      </div>
      ${spineT != null ? tScoreBar(spineT, P) : ''}
      ${ageNote}
    </div>
    <div class="row" ${s('gap:14px;flex:1;min-height:0;align-items:flex-start')}>
      <div ${s('flex-shrink:0;display:flex;flex-direction:column;gap:6px;align-items:center')}>
        <img src="${images.spine_url}" alt="Spine scan"
             ${s('height:320px;width:auto;border-radius:8px;display:block')}
             onerror="this.style.display='none'">
        <div ${s(`font-size:9px;color:${P.gray};letter-spacing:.4px`)}>AP Lumbar Spine</div>
      </div>
      <div class="card" ${s('flex:1')}>
        <div class="sec">L1–L4 Vertebral Detail</div>
        ${bmdTable(spineRows, P)}
      </div>
    </div>
    ${scanFootnotes([
      'Precision (LSC): ±0.010 g/cm² for AP Spine L1–L4 (68% CI; repeat scans within this range may reflect measurement variability)',
      'Reference: USA NHANES + GE Lunar (ages 20–40) AP Spine normative database. T-scores may not reflect Indian population norms.',
    ], P)}
  </div>
</div>`
}

/* ── Page 2: Dual Femur ──────────────────────────────────────────────────── */
function page2(data: OsteoReportData, P: Pal, lh: boolean, pageNum: number, total: number) {
  const { patient: pt, left_femur: lf, right_femur: rf, summary, images } = data
  const hasLeft  = Object.keys(lf).length > 0
  const hasRight = Object.keys(rf).length > 0

  const lfRows: [string, OsteoRegion | undefined, boolean][] = [
    ['Neck',       lf.Neck,       false],
    ['Trochanter', lf.Trochanter, false],
    ['Ward\'s',   lf.Wards,      false],
    ['Total',      lf.Total,      true ],
  ]
  const rfRows: [string, OsteoRegion | undefined, boolean][] = [
    ['Neck',       rf.Neck,       false],
    ['Trochanter', rf.Trochanter, false],
    ['Ward\'s',   rf.Wards,      false],
    ['Total',      rf.Total,      true ],
  ]

  const hipSiteLabel = summary.lowest_hip_side
    ? (summary.hip_bilateral
        ? 'femoral neck bilaterally'
        : `${summary.lowest_hip_side} femoral neck`)
    : ''
  const lowestSideNote = summary.lowest_hip_t != null
    ? `ISCD diagnostic T-score: <strong ${s(`color:${classColor(summary.overall_class)}`)}>${summary.lowest_hip_t >= 0 ? '+' : ''}${summary.lowest_hip_t.toFixed(1)}</strong>${hipSiteLabel ? ` — ${hipSiteLabel}` : ''}`
    : ''

  const symmetry = summary.left_neck_t != null && summary.right_neck_t != null
    ? Math.abs(summary.left_neck_t - summary.right_neck_t)
    : null

  return `
<div class="page">
  ${header(pt, 'Hip Bone Density — Dual Femur', P, lh, pageNum, total)}
  <div class="col" ${s('flex:1;gap:14px;min-height:0')}>
    <div class="card" ${s(`background:${classBg(summary.overall_class, P)};flex-shrink:0`)}>
      <div class="row" ${s('align-items:flex-end;gap:24px;margin-bottom:10px')}>
        <div ${s('flex:1')}>
          <div class="lbl">Hip Classification</div>
          <div ${s('margin-top:8px')}>${classBadge(summary.overall_class)}</div>
          <div ${s(`font-size:11px;color:${P.gray};margin-top:8px;line-height:1.6`)}>${lowestSideNote}</div>
          ${symmetry != null ? `
          <div ${s(`font-size:10px;color:${symmetry > 0.5 ? C.amber : P.gray};margin-top:4px`)}>
            L/R Neck symmetry: Δ${symmetry.toFixed(1)} T-score
            ${symmetry > 0.5 ? '— asymmetry &gt;0.5 warrants clinical attention' : ''}
          </div>` : ''}
        </div>
        ${summary.lowest_hip_t != null ? `
        <div ${s('display:flex;flex-direction:column')}>
          <div class="lbl">ISCD Diagnostic Hip T-Score</div>
          <div ${s(`font-size:9px;color:${P.gray};margin-top:2px`)}>Femoral Neck / Total Hip only</div>
          <div ${s('flex:1;min-height:12px')}></div>
          <div ${s(`font-size:38px;font-weight:800;color:${classColor(summary.overall_class)};line-height:1;margin-top:4px`)}>${summary.lowest_hip_t >= 0 ? '+' : ''}${summary.lowest_hip_t.toFixed(1)}</div>
        </div>` : ''}
      </div>
      ${summary.lowest_hip_t != null ? tScoreBar(summary.lowest_hip_t, P) : ''}
    </div>
    <div class="row" ${s('gap:14px;flex-shrink:0')}>
      ${hasLeft ? `
      <div ${s('flex:1;display:flex;align-items:center;justify-content:center;overflow:hidden;border-radius:8px;max-height:200px')}>
        <img src="${images.left_femur_url}" alt="Left femur"
             ${s('height:200px;width:auto;display:block;border-radius:8px')}
             onerror="this.style.display='none'">
      </div>` : ''}
      ${hasRight ? `
      <div ${s('flex:1;display:flex;align-items:center;justify-content:center;overflow:hidden;border-radius:8px;max-height:200px')}>
        <img src="${images.right_femur_url}" alt="Right femur"
             ${s('height:200px;width:auto;display:block;border-radius:8px')}
             onerror="this.style.display='none'">
      </div>` : ''}
    </div>
    <div class="row" ${s('gap:14px;flex-shrink:0')}>
      ${hasLeft ? `
      <div class="card" ${s('flex:1')}>
        <div class="sec">Left Femur</div>
        ${bmdTable(lfRows, P)}
      </div>` : ''}
      ${hasRight ? `
      <div class="card" ${s('flex:1')}>
        <div class="sec">Right Femur</div>
        ${bmdTable(rfRows, P)}
      </div>` : ''}
    </div>
    <div class="card" ${s('flex-shrink:0')}>
      <div class="sec">Understanding Hip Scores</div>
      <div class="row" ${s('gap:14px')}>
        <div ${s(`flex:1;background:${P.bg};border-radius:6px;padding:10px 14px;font-size:10px;color:${P.gray};line-height:1.7`)}>
          <strong ${s(`color:${P.text}`)}>ISCD 2019:</strong> Only Femoral Neck and Total Hip are used for WHO classification.
          Trochanter and Ward's Triangle are shown for completeness but are <em>not</em> diagnostic sites —
          their lower T-scores do not change the classification.
        </div>
        <div ${s(`flex:1;background:${P.bg};border-radius:6px;padding:10px 14px;font-size:10px;color:${P.gray};line-height:1.7`)}>
          <strong ${s(`color:${P.text}`)}>Z-Score ≤ −2.0</strong> indicates "below expected range for age and sex" and warrants
          investigation for secondary causes regardless of T-score. Relevant especially for premenopausal women and men under 50.
        </div>
      </div>
    </div>
    ${scanFootnotes([
      'Precision (LSC): ±0.012 g/cm² for Femoral Total (68% CI; repeat scans within this range may reflect measurement variability)',
      'Reference: USA NHANES + GE Lunar (ages 20–40) Femur normative database. T-scores may not reflect Indian population norms.',
    ], P)}
  </div>
</div>`
}

/* ── Page 3: Clinical Summary ────────────────────────────────────────────── */
function page3(data: OsteoReportData, P: Pal, lh: boolean, pageNum: number, total: number) {
  const { patient: pt, summary } = data
  const cls = summary.overall_class
  const clsColor = classColor(cls)

  const recommendations: { title: string; body: string; status: string }[] = []

  // Main diagnosis
  if (summary.premenopausal) {
    recommendations.push({
      status: cls === 'normal' ? 'good' : 'alert',
      title: `Bone Status: ${cls === 'normal' ? 'Normal' : 'Below Expected Range for Age'}`,
      body: `Z-Score ${summary.spine_z?.toFixed(1) ?? '—'} (spine) — premenopausal women under 50 are assessed by Z-score, not T-score. Z ≤ −2.0 indicates bone density below expected range and warrants secondary cause investigation.`,
    })
  } else {
    recommendations.push({
      status: cls === 'osteoporosis' ? 'alert' : cls === 'osteopenia' ? 'warn' : 'good',
      title: `WHO Classification: ${classLabel(cls)}`,
      body: cls === 'osteoporosis'
        ? `T-score ${summary.spine_t?.toFixed(1) ?? summary.lowest_hip_t?.toFixed(1) ?? '—'} — meets WHO criterion for osteoporosis (T ≤ −2.5). Clinical correlation and FRAX fracture risk assessment strongly recommended.`
        : cls === 'osteopenia'
          ? `T-score indicates reduced bone mass. Lifestyle optimisation (calcium, vitamin D, weight-bearing exercise) advised. Recheck in 1–2 years.`
          : `T-score within normal range. Maintain bone health with adequate calcium (1000–1200 mg/day), vitamin D (600–800 IU/day), and weight-bearing exercise.`,
    })
  }

  // Fracture risk
  if (cls === 'osteoporosis') {
    recommendations.push({
      status: 'alert',
      title: 'FRAX Assessment Recommended',
      body: `T-score in the osteoporotic range. FRAX (WHO fracture risk assessment tool) should be calculated to quantify 10-year fracture probability and guide treatment decisions.`,
    })
    recommendations.push({
      status: 'alert',
      title: 'Pharmacological Review',
      body: `Bisphosphonates (alendronate, risedronate) or other anti-resorptive agents may be clinically indicated. Discussion with treating clinician or endocrinologist recommended.`,
    })
  }

  // Nutrition
  recommendations.push({
    status: 'info',
    title: 'Calcium & Vitamin D',
    body: cls === 'osteoporosis'
      ? `Ensure Calcium 1200 mg/day + Vitamin D 1000–2000 IU/day. Measure serum 25-OHD to confirm sufficiency. Supplement if dietary intake is insufficient.`
      : `Calcium 1000–1200 mg/day (diet preferred; supplement if needed). Vitamin D 600–800 IU/day. Annual 25-OHD check recommended.`,
  })

  // Exercise
  recommendations.push({
    status: 'info',
    title: 'Exercise Prescription',
    body: cls === 'osteoporosis'
      ? `Progressive resistance training to stimulate bone remodelling. Balance training and fall prevention programme recommended. Avoid high-impact activities that risk fragility fracture until treatment is established.`
      : `Weight-bearing aerobic exercise (walking, jogging) plus resistance training 2–3× per week. Both are independently beneficial for bone mineral density maintenance.`,
  })

  // Secondary causes
  if (summary.premenopausal || summary.spine_z != null && summary.spine_z <= -2) {
    recommendations.push({
      status: 'warn',
      title: 'Secondary Cause Workup',
      body: `Z-score below expected range for age. Consider secondary causes: malabsorption (coeliac, IBD), vitamin D deficiency, hypogonadism, hyperparathyroidism, thyroid disease, steroid use, or low body weight.`,
    })
  }

  // Follow-up
  recommendations.push({
    status: 'info',
    title: 'Follow-up DXA',
    body: cls === 'osteoporosis'
      ? `Repeat DXA in 1–2 years to monitor treatment response. Earlier if pharmacological therapy is initiated.`
      : cls === 'osteopenia'
        ? `Repeat DXA in 1–2 years. Sooner if risk factors develop or treatment is started.`
        : `Repeat DXA in 2–3 years or when risk factors change.`,
  })

  const statusStyle = (st: string) => ({
    good:  { bg: P.statusGood,  border: C.greenLt },
    warn:  { bg: P.statusWarn,  border: C.amber   },
    alert: { bg: P.statusAlert, border: C.red     },
    info:  { bg: P.statusInfo,  border: C.tealLt  },
  }[st] ?? { bg: P.card, border: P.border })

  const cards = recommendations.map(item => {
    const st = statusStyle(item.status)
    return `
    <div ${s(`background:${st.bg};border:1px solid ${st.border}40;border-left:4px solid ${st.border};border-radius:6px;padding:14px 18px`)}>
      <div ${s(`font-size:13px;font-weight:700;color:${st.border};margin-bottom:5px`)}>${item.title}</div>
      <div ${s(`font-size:11px;color:${P.grayLt};line-height:1.65`)}>${item.body}</div>
    </div>`
  }).join('')

  const foot = `
  <div class="page-footer" ${s(`flex-shrink:0;margin-top:10px;border-top:1px solid ${P.border};padding-top:7px;font-size:9px;color:${P.gray};line-height:1.7`)}>
    WHO criteria (T ≤−2.5 osteoporosis, −2.5&lt;T≤−1.0 osteopenia) apply to postmenopausal women and men ≥50.
    South Asian-specific normative data not available on GE Lunar DPX-NT — benchmarked against White/Caucasian population.
    Scanner ${esc(pt.scanner)} · ${esc(pt.software)} · Scan ${esc(pt.scan_date)} · For clinical use only — interpret with a qualified clinician.
  </div>`

  return `
<div class="page">
  ${header(pt, 'Clinical Summary & Recommendations', P, lh, pageNum, total)}
  <div ${s('flex-shrink:0;display:flex;align-items:center;gap:16px;padding:12px 16px;border-radius:8px;margin-bottom:14px;background:' + clsColor + '18;border:1px solid ' + clsColor + '44')}>
    <div ${s(`font-size:36px;font-weight:800;color:${clsColor};line-height:1`)}>${classLabel(cls)}</div>
    <div ${s(`font-size:11px;color:${P.gray};line-height:1.7`)}>
      Lowest T-score: <strong ${s(`color:${clsColor}`)}>${summary.lowest_hip_t != null ? (summary.lowest_hip_t >= 0 ? '+' : '') + summary.lowest_hip_t.toFixed(1) : summary.spine_t != null ? (summary.spine_t >= 0 ? '+' : '') + summary.spine_t.toFixed(1) : '—'}</strong>
      &nbsp;·&nbsp; Spine L1–L4: ${summary.spine_t != null ? (summary.spine_t >= 0 ? '+' : '') + summary.spine_t.toFixed(1) : '—'}
      ${summary.lowest_hip_t != null ? `&nbsp;·&nbsp; Hip: ${(summary.lowest_hip_t >= 0 ? '+' : '') + summary.lowest_hip_t.toFixed(1)} (${summary.lowest_hip_side})` : ''}
    </div>
  </div>
  <div ${s('flex:1;display:grid;grid-template-columns:1fr 1fr;grid-auto-rows:auto;align-content:start;gap:12px;min-height:0')}>
    ${cards}
  </div>
  ${foot}
</div>`
}

/* ── Entry point ─────────────────────────────────────────────────────────── */
export function generateOsteoHtml(
  data: OsteoReportData,
  dark = false,
  letterhead = false,
): string {
  const P = dark && !letterhead ? darkPal : lightPal
  const pages = [page1, page2, page3]
  const total = pages.length
  return `<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<title>BMD Report — ${esc(data.patient.name)}</title>
<style>${css(P, letterhead)}</style></head><body>
${pages.map((fn, i) => fn(data, P, letterhead, i + 1, total)).join('')}
</body></html>`
}
