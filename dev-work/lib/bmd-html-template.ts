import type { ReportData, RegionComposition } from './bmd-types'

/* ── palette ─────────────────────────────────────────────────────────────── */
const C = {
  teal: '#0D7377', tealLt: '#14a8ae',
  pink: '#E91E8C', cyan: '#00BCD4', bone: '#B0BEC5',
  green: '#2E7D32', greenLt: '#4CAF50',
  amber: '#E65100', red: '#B71C1C',
}

type Pal = {
  bg: string; card: string; border: string;
  text: string; gray: string; grayLt: string;
  cardHighlight: string;
  statusGood: string; statusWarn: string; statusAlert: string; statusInfo: string;
}

const darkPal: Pal = {
  bg: '#0D1B2A', card: '#0f2235', border: '#1a3a55',
  text: '#FFFFFF', gray: '#9E9E9E', grayLt: '#CFD8DC',
  cardHighlight: '#0a1f30',
  statusGood: '#0a2a0a', statusWarn: '#2a1a00', statusAlert: '#2a0a0a', statusInfo: '#0a1a2a',
}

const lightPal: Pal = {
  bg: '#f5f7fa', card: '#ffffff', border: '#d0dce8',
  text: '#1a1a2e', gray: '#6b7280', grayLt: '#374151',
  cardHighlight: '#e8f4fb',
  statusGood: '#e8f5e8', statusWarn: '#fff3e0', statusAlert: '#fce8e8', statusInfo: '#e3f2fd',
}

/* Pages use height:297mm + flex-column so content is distributed to fill the full A4 sheet. */
const darkCss = `
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:${darkPal.bg};font-family:'Inter',sans-serif;color:${darkPal.text};
       -webkit-print-color-adjust:exact;print-color-adjust:exact}
  .page{width:210mm;height:297mm;padding:10mm 13mm;margin:0 auto;
        background:${darkPal.bg};page-break-after:always;position:relative;
        display:flex;flex-direction:column;overflow:hidden}
  .page:last-child{page-break-after:auto}
  @page{size:A4;margin:0}
  .row{display:flex;gap:14px}
  .col{display:flex;flex-direction:column}
  .card{background:${darkPal.card};border:1px solid ${darkPal.border};border-radius:8px;padding:16px}
  .lbl{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.8px;color:${darkPal.gray}}
  .sec{font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:${C.tealLt};margin-bottom:10px}
  .tag{display:inline-block;padding:4px 12px;border-radius:3px;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.5px}
`

const lightCss = `
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:#f5f7fa;font-family:'Inter',sans-serif;color:#1a1a2e;
       -webkit-print-color-adjust:exact;print-color-adjust:exact}
  .page{width:210mm;height:297mm;padding:10mm 13mm;margin:0 auto;
        background:#f5f7fa;page-break-after:always;position:relative;
        display:flex;flex-direction:column;overflow:hidden}
  .page:last-child{page-break-after:auto}
  @page{size:A4;margin:0}
  .row{display:flex;gap:14px}
  .col{display:flex;flex-direction:column}
  .card{background:#ffffff;border:1px solid #d0dce8;border-radius:8px;padding:16px}
  .lbl{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.8px;color:#6b7280}
  .sec{font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#0D7377;margin-bottom:10px}
  .tag{display:inline-block;padding:4px 12px;border-radius:3px;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.5px}
`

/* Letterhead: pre-printed stationery, top 35mm + bottom 28mm reserved. */
const letterheadCss = `
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:#ffffff;font-family:'Inter',sans-serif;color:#1a1a2e;
       -webkit-print-color-adjust:exact;print-color-adjust:exact}
  .page{width:210mm;min-height:234mm;padding:6mm 15mm 6mm 15mm;margin:0 auto;
        background:#ffffff;page-break-after:always;position:relative;
        display:flex;flex-direction:column}
  .page:last-child{page-break-after:auto}
  @page{size:A4;margin:35mm 15mm 28mm 15mm}
  .row{display:flex;gap:14px}
  .col{display:flex;flex-direction:column}
  .card{background:#f8fafb;border:1px solid #d0dce8;border-radius:6px;padding:14px}
  .lbl{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.8px;color:#6b7280}
  .sec{font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#0D7377;margin-bottom:10px}
  .tag{display:inline-block;padding:4px 12px;border-radius:3px;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.5px}
  .page-logo-row{display:none}
  .page-footer{display:none}
`

export function generateReportHtml(data: ReportData, dark = true, letterhead = false, fatMode = false): string {
  const css = letterhead ? letterheadCss : dark ? darkCss : lightCss
  const P   = dark && !letterhead ? darkPal : lightPal
  const pages = fatMode
    ? [page2, page1, page3, page4, page5]
    : [page1, page2, page3, page4, page5]
  const total = pages.length
  return `<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<title>DEXA Report — ${esc(data.patient.name)}</title>
<style>${css}</style></head><body>
${pages.map((fn, i) => fn(data, P, letterhead, i + 1, total)).join('')}
</body></html>`
}

/* ── helpers ─────────────────────────────────────────────────────────────── */
function esc(s: string | number | undefined) {
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
}
function s(style: string) { return `style="${style}"` }

function header(pt: ReportData['patient'], title: string, P: Pal, lh = false, pageNum = 0, totalPages = 0) {
  const eth = pt.ethnicity || 'White'
  const pgTag = pageNum > 0
    ? `<span ${s(`font-size:10px;font-weight:500;color:${P.gray}`)}>Page ${pageNum} / ${totalPages}</span>`
    : ''

  const logoRow = lh ? '' : `
    <div class="page-logo-row" ${s('display:flex;justify-content:space-between;align-items:center;padding-bottom:8px;margin-bottom:8px;border-bottom:1px solid ' + P.border)}>
      <img src="/sdrc-logo.png" alt="SDRC Diagnostics" ${s(`height:36px;width:auto;border-radius:4px;padding:${P === darkPal ? '2px 4px' : '0'};background:${P === darkPal ? 'rgba(255,255,255,0.92)' : 'transparent'}`)}>
      <div ${s(`text-align:right;font-size:10px;color:${P.gray};line-height:1.7`)}>
        <div ${s(`color:${P.text};font-weight:700;font-size:11px`)}>${esc(pt.name)}</div>
        <div>${esc(pt.gender)} · ${pt.age}y · ${pt.height_cm} cm · ${pt.weight_entered_kg} kg</div>
        <div>ID: ${esc(pt.id)} · Scan: ${esc(pt.scan_date)} ${esc(pt.scan_time)}</div>
      </div>
    </div>`

  const patientCompact = lh ? `
    <div ${s(`display:flex;justify-content:space-between;align-items:baseline;margin-bottom:4px`)}>
      <div ${s(`font-size:20px;font-weight:800;color:${P.text};letter-spacing:.3px`)}>${esc(title)}</div>
      <div ${s('display:flex;align-items:baseline;gap:14px')}>
        <div ${s(`text-align:right;font-size:10px;color:${P.gray};line-height:1.5`)}>
          <span ${s(`color:${P.text};font-weight:700;font-size:11px`)}>${esc(pt.name)}</span>
          · ID: ${esc(pt.id)} · ${esc(pt.gender)} · ${pt.age}y · ${pt.height_cm} cm · ${pt.weight_entered_kg} kg
          · Scan ${esc(pt.scan_date)}
        </div>
        ${pgTag}
      </div>
    </div>` : `
    <div ${s('display:flex;justify-content:space-between;align-items:baseline')}>
      <div ${s(`font-size:20px;font-weight:800;color:${P.text};letter-spacing:.3px`)}>${esc(title)}</div>
      ${pgTag}
    </div>`

  return `
  <div ${s('margin-bottom:12px;flex-shrink:0')}>
    ${logoRow}
    <div ${s(`border-bottom:2px solid ${C.teal};padding-bottom:6px`)}>
      ${patientCompact}
    </div>
  </div>`
}

function compBar(fat: number, lean: number, bone: number, P: Pal) {
  const t  = fat + lean + bone
  const fp = (fat  / t * 100).toFixed(1)
  const lp = (lean / t * 100).toFixed(1)
  const bp = (bone / t * 100).toFixed(1)
  return `
  <div>
    <div ${s('display:flex;height:28px;border-radius:5px;overflow:hidden;margin-bottom:8px')}>
      <div ${s(`width:${fp}%;background:${C.pink}`)}></div>
      <div ${s(`width:${lp}%;background:${C.cyan}`)}></div>
      <div ${s(`width:${bp}%;background:${C.bone}`)}></div>
    </div>
    <div ${s(`display:flex;font-size:10px;color:${P.gray};justify-content:space-between`)}>
      <span><span ${s(`color:${C.pink}`)}>■</span> Fat ${fp}% (${(fat/1000).toFixed(1)} kg)</span>
      <span><span ${s(`color:${C.cyan}`)}>■</span> Lean ${lp}% (${(lean/1000).toFixed(1)} kg)</span>
      <span><span ${s(`color:${C.bone}`)}>■</span> BMC ${bp}% (${(bone/1000).toFixed(2)} kg)</span>
    </div>
  </div>`
}

function mrow(lbl: string, val: string, note: string, color: string, P: Pal) {
  return `
  <div ${s(`display:flex;justify-content:space-between;align-items:baseline;padding:7px 0;border-bottom:1px solid ${P.border}`)}>
    <div ${s(`font-size:11px;color:${P.gray}`)}>${esc(lbl)}</div>
    <div ${s('text-align:right')}>
      <div ${s(`font-size:14px;font-weight:700;color:${color}`)}>${esc(val)}</div>
      ${note ? `<div ${s(`font-size:9.5px;color:${P.gray}`)}>${esc(note)}</div>` : ''}
    </div>
  </div>`
}

function metricBox(lbl: string, val: string, unit: string, color: string, P: Pal, sub?: string) {
  return `
  <div class="card" ${s('flex:1;min-width:0;display:flex;flex-direction:column')}>
    <div class="lbl">${esc(lbl)}</div>
    <div ${s(`font-size:28px;font-weight:800;color:${color};line-height:1;margin-top:14px`)}>${esc(val)}</div>
    ${unit ? `<div ${s(`font-size:10px;color:${P.gray};margin-top:4px`)}>${esc(unit)}</div>` : ''}
    ${sub ? `<div ${s(`font-size:9px;color:${P.gray};margin-top:2px`)}>${esc(sub)}</div>` : ''}
  </div>`
}

function regionBarRow(name: string, d: RegionComposition, P: Pal) {
  return `
  <div ${s('display:flex;align-items:center;gap:10px;margin-bottom:12px')}>
    <div ${s(`width:44px;font-size:11px;font-weight:600;color:${P.grayLt}`)}>${esc(name)}</div>
    <div ${s('flex:1;display:flex;height:22px;border-radius:4px;overflow:hidden')}>
      <div ${s(`width:${d.fat_pct}%;background:${C.pink}`)}></div>
      <div ${s(`width:${d.lean_pct}%;background:${C.cyan}`)}></div>
      <div ${s(`width:${d.bone_pct}%;background:${C.bone}`)}></div>
    </div>
    <div ${s(`font-size:10px;color:${P.gray};min-width:190px;text-align:right`)}>
      <span ${s(`color:${C.pink}`)}>F ${d.fat_pct}%</span> ·
      <span ${s(`color:${C.cyan}`)}>L ${d.lean_pct}%</span> ·
      <span ${s(`color:${C.bone}`)}>BMC ${d.bone_pct}%</span>
      (${(d.total_g / 1000).toFixed(2)} kg)
    </div>
  </div>`
}

function regionDetail(d: RegionComposition, P: Pal) {
  const rows = [
    { lbl: 'Fat',  val: d.fat_g,  pct: d.fat_pct,  c: C.pink },
    { lbl: 'Lean', val: d.lean_g, pct: d.lean_pct, c: C.cyan },
    { lbl: 'BMC',  val: d.bone_g, pct: d.bone_pct, c: C.bone },
  ]
  return rows.map(r => `
  <div ${s('display:flex;align-items:center;gap:8px;margin-bottom:8px')}>
    <div ${s(`width:36px;font-size:11px;color:${r.c};font-weight:600`)}>${r.lbl}</div>
    <div ${s(`flex:1;height:14px;background:${P.border};border-radius:3px;overflow:hidden`)}>
      <div ${s(`width:${r.pct}%;height:100%;background:${r.c}`)}></div>
    </div>
    <div ${s(`width:90px;font-size:10px;color:${P.gray};text-align:right`)}>
      ${r.pct}% · ${(r.val / 1000).toFixed(2)} kg
    </div>
  </div>`).join('')
}

function fmiScale(fmi: number, gender: string, P: Pal) {
  const male = gender.toLowerCase().startsWith('m')
  const max  = male ? 15 : 18
  const pct  = Math.min(Math.max(fmi / max * 100, 1), 99)
  const zones = male
    ? [{ w: 40,   lbl: 'Normal &lt;6', c: C.green },
       { w: 20,   lbl: 'Elevated 6–9', c: C.amber },
       { w: 40,   lbl: 'Obese &gt;9',  c: C.red   }]
    : [{ w: 50,   lbl: 'Normal &lt;9', c: C.green },
       { w: 22.2, lbl: 'Elevated 9–13',c: C.amber },
       { w: 27.8, lbl: 'Obese &gt;13', c: C.red   }]
  const col = fmi < (male ? 6 : 9) ? C.greenLt : fmi < (male ? 9 : 13) ? C.amber : C.red
  return `
  <div>
    <div ${s('position:relative;margin-bottom:8px')}>
      <div ${s('display:flex;height:22px;border-radius:5px;overflow:hidden')}>
        ${zones.map(z => `<div ${s(`width:${z.w}%;background:${z.c}`)}></div>`).join('')}
      </div>
      <div ${s(`position:absolute;left:${pct}%;top:-4px;bottom:-4px;width:4px;background:${P.text};border-radius:2px;transform:translateX(-50%)`)}></div>
    </div>
    <div ${s(`display:flex;justify-content:space-between;font-size:9px;color:${P.gray};margin-bottom:8px`)}>
      ${zones.map(z => `<span>${z.lbl}</span>`).join('')}
    </div>
    <div ${s(`font-size:15px;font-weight:700;color:${col}`)}>
      Your FMI: ${fmi} kg/m²
      <span ${s(`font-size:10px;font-weight:400;color:${P.gray};margin-left:8px`)}>(fat kg ÷ height m²)</span>
    </div>
  </div>`
}

function agChart(comp: ReportData['composition'], gender: string, P: Pal) {
  const { android_fat_pct: afp, gynoid_fat_pct: gfp, ag_ratio: ag } = comp
  const android = comp.regions.Android, gynoid = comp.regions.Gynoid
  const male = gender.toLowerCase().startsWith('m')
  const agColor = ag < 0.8 ? C.greenLt : ag < 1.0 ? C.amber : C.red

  const interp = male
    ? ag < 0.8
      ? 'Fat stored predominantly in hips and thighs — below the typical male distribution. Favourable metabolic profile.'
      : ag < 1.0
        ? 'Balanced fat distribution within the normal range for male body composition.'
        : 'Mild central fat predominance, common in male body composition patterns. Monitor abdominal fat trend over time.'
    : ag < 0.8
      ? 'Favourable gynoid distribution typical of female body composition. Lower cardiometabolic risk profile.'
      : ag < 1.0
        ? 'Mixed distribution with slight central tendency relative to the typical female fat pattern. Monitor over time.'
        : 'Increased abdominal fat distribution relative to the expected female fat pattern. Associated with higher cardiometabolic risk in women.'

  const sideBars = android && gynoid ? `
  <div ${s('display:flex;gap:14px;margin-top:14px')}>
    ${[
      { name: 'Android (Abdominal)', d: android, fatPct: afp },
      { name: 'Gynoid (Hip / Thigh)',  d: gynoid,  fatPct: gfp  },
    ].map(({ name, d, fatPct }) => `
    <div ${s('flex:1')}>
      <div ${s(`font-size:11px;font-weight:600;color:${P.grayLt};margin-bottom:6px`)}>${name}</div>
      <div ${s('display:flex;height:32px;border-radius:4px;overflow:hidden')}>
        <div ${s(`width:${d.fat_pct}%;background:${C.pink};display:flex;align-items:center;justify-content:center`)}>
          ${d.fat_pct > 12 ? `<span ${s('font-size:10px;font-weight:700;color:#fff')}>${d.fat_pct}%</span>` : ''}
        </div>
        <div ${s(`width:${d.lean_pct}%;background:${C.cyan};display:flex;align-items:center;justify-content:center`)}>
          ${d.lean_pct > 12 ? `<span ${s(`font-size:10px;font-weight:700;color:${P.bg}`)}>${d.lean_pct}%</span>` : ''}
        </div>
        <div ${s(`width:${d.bone_pct}%;background:${C.bone}`)}></div>
      </div>
      <div ${s(`font-size:10px;color:${P.gray};margin-top:6px;line-height:1.9`)}>
        <div><span ${s(`color:${C.pink}`)}>■</span> Fat: ${fatPct}% · ${(d.fat_g/1000).toFixed(2)} kg</div>
        <div><span ${s(`color:${C.cyan}`)}>■</span> Lean: ${d.lean_pct}% · ${(d.lean_g/1000).toFixed(2)} kg</div>
        <div ${s(`color:${d.lean_pct > 60 ? C.cyan : P.gray};font-weight:${d.lean_pct > 60 ? 600 : 400}`)}>
          ${d.lean_pct > 60 ? 'Muscle-dominant ✓' : 'Mixed composition'}
        </div>
      </div>
    </div>`).join('')}
  </div>` : ''

  return `
  <div>
    <div ${s('display:flex;align-items:center;gap:16px;margin-bottom:6px')}>
      <div>
        <div class="lbl">A/G Fat % Ratio</div>
        <div ${s(`font-size:44px;font-weight:800;color:${agColor};line-height:1`)}>${ag}</div>
        <div ${s(`font-size:11px;color:${agColor};font-weight:600;margin-top:6px`)}>${interp}</div>
        <div ${s(`font-size:10px;color:${P.gray};margin-top:8px;line-height:1.7`)}>
          <span ${s(`color:${C.greenLt};font-weight:700`)}>&lt;0.80 Gynoid</span> ·
          <span ${s(`color:${C.amber};font-weight:700`)}>0.80–1.0 Intermediate</span> ·
          <span ${s(`color:${C.red};font-weight:700`)}>&gt;1.0 Android</span>
        </div>
      </div>
    </div>
    ${sideBars}
  </div>`
}

function whoViz(t: number, P: Pal) {
  const pct = Math.min(Math.max(((t + 4) / 8) * 100, 1), 99)
  return `
  <div>
    <div ${s('position:relative;margin-bottom:8px')}>
      <div ${s('display:flex;height:30px;border-radius:5px;overflow:hidden')}>
        <div ${s(`width:18.75%;background:${C.red};display:flex;align-items:center;justify-content:center`)}>
          <span ${s('font-size:9px;color:#fff;font-weight:700')}>Osteoporosis</span></div>
        <div ${s(`width:18.75%;background:${C.amber};display:flex;align-items:center;justify-content:center`)}>
          <span ${s('font-size:9px;color:#fff;font-weight:700')}>Osteopenia</span></div>
        <div ${s(`width:62.5%;background:${C.green};display:flex;align-items:center;justify-content:center`)}>
          <span ${s('font-size:9px;color:#fff;font-weight:700')}>Normal Bone Density</span></div>
      </div>
      <div ${s(`position:absolute;left:${pct}%;top:-6px;width:5px;height:42px;background:${P.text};border-radius:2px;transform:translateX(-50%);box-shadow:0 0 4px rgba(0,0,0,.5)`)}></div>
    </div>
    <div ${s(`display:flex;justify-content:space-between;font-size:9px;color:${P.gray}`)}>
      <span>−4</span><span>−2.5</span><span>−1</span><span>0</span><span>+4</span>
    </div>
  </div>`
}

function scoreBlock(lbl: string, val: number, meaning: string, P: Pal) {
  const col = val <= -2.5 ? C.red : val <= -1 ? C.amber : C.greenLt
  const sign = val >= 0 ? '+' : ''
  return `
  <div ${s('display:flex;flex-direction:column')}>
    <div class="lbl">${esc(lbl)}</div>
    <div ${s(`font-size:9px;color:${P.gray};margin-top:2px`)}>${meaning}</div>
    <div ${s('flex:1;min-height:8px')}></div>
    <div ${s(`font-size:38px;font-weight:800;color:${col};line-height:1;margin-top:4px`)}>${sign}${val.toFixed(1)}</div>
  </div>`
}

function boneClassBadge(cls: string) {
  const cfg = {
    normal:       { lbl: 'Normal Bone Density', c: C.greenLt },
    low_mass:     { lbl: 'Osteopenia',           c: C.amber   },
    osteoporosis: { lbl: 'Osteoporosis',         c: C.red     },
  }[cls] ?? { lbl: cls, c: darkPal.gray }
  return `<span class="tag" ${s(`color:${cfg.c};background:${cfg.c}22;border:1px solid ${cfg.c}44`)}>${cfg.lbl}</span>`
}

function almiBadge(rating: string) {
  const cfg = {
    low:    { lbl: 'Low Muscle Mass',  c: C.amber   },
    normal: { lbl: 'Normal Muscle',    c: C.greenLt },
    high:   { lbl: 'High Muscle Mass', c: C.cyan    },
  }[rating] ?? { lbl: rating, c: darkPal.gray }
  return `<span class="tag" ${s(`color:${cfg.c};background:${cfg.c}22;border:1px solid ${cfg.c}44`)}>${cfg.lbl}</span>`
}

function boneCardBg(cls: string, P: Pal) {
  return cls === 'osteoporosis' ? P.statusAlert : cls === 'low_mass' ? P.statusWarn : P.statusGood
}

function boneColor(cls: string) {
  return cls === 'osteoporosis' ? C.red : cls === 'low_mass' ? C.amber : C.greenLt
}

function bodyFatRefCard(fatPct: number, gender: string, P: Pal) {
  const male = gender.toLowerCase().startsWith('m')
  type Zone = { lbl: string; range: string; w: number; c: string; lo?: number; hi?: number }
  const zones: Zone[] = male
    ? [{ lbl: 'Athletic', range: '<14%',   w: 40,   c: C.greenLt, hi: 14 },
       { lbl: 'Fit',      range: '14–18%', w: 11.4, c: C.tealLt,  lo: 14, hi: 18 },
       { lbl: 'Normal',   range: '18–25%', w: 20,   c: C.amber,   lo: 18, hi: 25 },
       { lbl: 'Excess',   range: '>25%',   w: 28.6, c: C.red,     lo: 25 }]
    : [{ lbl: 'Athletic', range: '<21%',   w: 46.7, c: C.greenLt, hi: 21 },
       { lbl: 'Fit',      range: '21–25%', w: 8.9,  c: C.tealLt,  lo: 21, hi: 25 },
       { lbl: 'Normal',   range: '25–32%', w: 15.6, c: C.amber,   lo: 25, hi: 32 },
       { lbl: 'Excess',   range: '>32%',   w: 28.9, c: C.red,     lo: 32 }]
  const maxScale = male ? 35 : 45
  const markerPct = Math.min(Math.max(fatPct / maxScale * 100, 1), 99)
  const zone = zones.find(z => fatPct >= (z.lo ?? 0) && fatPct < (z.hi ?? Infinity))
  const markerColor = zone?.c ?? P.gray
  return `
  <div class="card" ${s('flex-shrink:0')}>
    <div class="sec">Body Fat % Reference (${male ? 'Men' : 'Women'}) — ACE Categories</div>
    <div ${s('position:relative;margin-bottom:6px')}>
      <div ${s('display:flex;height:14px;border-radius:4px;overflow:hidden')}>
        ${zones.map(z => `<div ${s(`width:${z.w}%;background:${z.c}`)}></div>`).join('')}
      </div>
      <div ${s(`position:absolute;left:${markerPct}%;top:-4px;bottom:-4px;width:3px;background:${P.text};border-radius:2px;transform:translateX(-50%);box-shadow:0 0 3px rgba(0,0,0,.5)`)}></div>
    </div>
    <div ${s('display:flex;justify-content:space-between;font-size:9px;margin-top:4px')}>
      ${zones.map(z => `<div><span ${s(`color:${z.c};font-weight:700`)}>${z.lbl}</span> <span ${s(`color:${P.gray}`)}>${z.range}</span></div>`).join('')}
    </div>
    <div ${s(`font-size:10px;margin-top:8px;border-top:1px solid ${P.border};padding-top:6px;color:${P.gray}`)}>
      Patient body fat: <strong ${s(`color:${markerColor}`)}>${fatPct}%</strong>
      <span ${s(`color:${zone?.c ?? P.gray};font-weight:600;margin-left:8px`)}>${zone?.lbl ?? ''} range</span>
    </div>
  </div>`
}

function muscleContextCard(P: Pal) {
  return `
  <div class="card" ${s('flex-shrink:0')}>
    <div class="sec">Why Muscle Mass Matters</div>
    <div ${s(`font-size:10.5px;color:${P.gray};line-height:1.85`)}>
      Skeletal muscle mass peaks around age 25–30 and naturally declines
      <strong ${s(`color:${P.text}`)}>3–8% per decade</strong> (sarcopenia). Low appendicular lean mass is
      independently linked to reduced strength, impaired mobility, insulin resistance, and higher
      all-cause mortality risk.<br>
      <span ${s(`color:${C.tealLt};font-weight:600`)}>▸ Resistance training</span> 2–3× per week stimulates muscle protein synthesis at any age.<br>
      <span ${s(`color:${C.tealLt};font-weight:600`)}>▸ Protein intake</span> of ≥ 1.6 g/kg body weight/day is the minimum recommended for muscle maintenance.
    </div>
  </div>`
}

function boneGuideCard(cls: string, P: Pal) {
  const { title, color, items } = cls === 'normal' ? {
    title: 'Bone Health — Maintenance', color: C.greenLt,
    items: [
      'Calcium 1000–1200 mg/day through diet (dairy, leafy greens, fortified foods) or supplementation.',
      'Vitamin D 600–800 IU/day; check serum 25-OHD annually to confirm sufficiency.',
      'Regular weight-bearing activity: walking, jogging, resistance training, and balance work.',
      'Recheck BMD in 2–3 years or sooner if risk factors change.',
    ],
  } : cls === 'low_mass' ? {
    title: 'Bone Health — Prevention Priorities', color: C.amber,
    items: [
      'Calcium 1200 mg/day + Vitamin D 800–1000 IU/day; supplement if dietary intake is insufficient.',
      'Progressive resistance and weight-bearing exercise to stimulate bone remodelling.',
      'Avoid smoking and limit alcohol — both accelerate bone loss significantly.',
      'Discuss pharmacological options (bisphosphonates, hormone therapy) with your clinician.',
      'Repeat DXA in 1–2 years to track progression.',
    ],
  } : {
    title: 'Bone Health — Clinical Review Recommended', color: C.red,
    items: [
      'FRAX fracture risk assessment recommended — discuss with your clinician promptly.',
      'Anti-resorptive therapy (bisphosphonates) or anabolic agents may be clinically indicated.',
      'Calcium 1200 mg/day + Vitamin D 1000–2000 IU/day.',
      'Fall prevention: balance training, home safety review, medication review for fall risk.',
      'Avoid high-impact activities that risk fragility fracture until treatment is established.',
    ],
  }
  return `
  <div class="card" ${s(`flex-shrink:0;border-left:3px solid ${color}`)}>
    <div class="sec">${title}</div>
    <div ${s(`font-size:10.5px;color:${P.gray};line-height:1.9`)}>
      ${items.map(i => `<div>▸ ${i}</div>`).join('')}
    </div>
  </div>`
}

/* ── Pages ───────────────────────────────────────────────────────────────── */

function page1(data: ReportData, P: Pal, lh = false, pageNum = 1, totalPages = 5) {
  const { patient: pt, composition: comp, computed: calc } = data
  const bmiNote = (bmi: number) =>
    bmi < 18.5 ? 'Underweight' : bmi < 25 ? 'Normal weight' : bmi < 30 ? 'Overweight' : 'Obese class I+'
  const almiNote = (r: string) =>
    r === 'high' ? '● Excellent — above reference' : r === 'low' ? '▲ Below reference' : '● Within normal range'
  const fmiNote = (r: string) =>
    r === 'low' ? 'Normal (men <6 / women <9 kg/m²)' : r === 'moderate' ? '▲ Borderline elevated' : '▲ Elevated'

  return `
<div class="page">
  ${header(pt, 'Body Composition Summary', P, lh, pageNum, totalPages)}
  <div ${s('flex:1;display:flex;gap:16px;min-height:0')}>
    <div ${s('width:160px;flex-shrink:0;display:flex;flex-direction:column')}>
      <img src="${data.images.composite_url}" alt="body composition + bone"
           ${s('width:100%;flex:1;object-fit:contain;border-radius:6px;min-height:0')}>
      <div ${s(`text-align:center;margin-top:6px;font-size:9.5px;color:${P.gray};flex-shrink:0`)}>
        <span ${s(`color:${C.pink}`)}>■</span> Fat &nbsp;
        <span ${s(`color:${C.cyan}`)}>■</span> Lean &nbsp;
        <span ${s('color:#e0ffe0')}>■</span> Bone overlay
      </div>
    </div>
    <div class="col" ${s('flex:1;gap:12px;min-height:0')}>
      <div class="row" ${s('gap:12px;flex-shrink:0')}>
        ${metricBox('Body Fat',  `${comp.fat_pct}`,                   '%',        C.pink,    P, comp.centile ? `Centile ${comp.centile}` : undefined)}
        ${metricBox('Fat Mass',  `${(comp.fat_g/1000).toFixed(1)}`,   'kg',       C.pink,    P)}
        ${metricBox('Lean Mass', `${(comp.lean_g/1000).toFixed(1)}`,  'kg',       C.cyan,    P)}
        ${metricBox('RMR',       `${calc.rmr_kcal.toLocaleString()}`, 'kcal/day', C.tealLt,  P, 'Katch-McArdle')}
      </div>
      <div class="card" ${s('flex-shrink:0')}>
        <div class="sec">Body Composition</div>
        ${compBar(comp.fat_g, comp.lean_g, comp.bmc_g, P)}
      </div>
      <div class="card" ${s('flex-shrink:0')}>
        <div class="sec">Body &amp; Lean Mass Indices</div>
        ${calc.alm_available
          ? mrow('ALM — Appendicular Lean Mass', `${calc.alm_kg} kg`, 'Arms + Legs lean', C.cyan, P)
          : mrow('ALM — Appendicular Lean Mass', 'N/A', 'Requires MDB regional data', P.gray, P)}
        ${calc.alm_available
          ? mrow('ALMI — Lean Mass Index', `${calc.almi} kg/m²`, almiNote(calc.almi_rating), C.cyan, P)
          : mrow('ALMI — Lean Mass Index', 'N/A', 'Not computable without regional breakdown', P.gray, P)}
        ${mrow('LMI — Lean Mass Index', `${calc.lmi} kg/m²`, 'Total lean ÷ height²', C.cyan, P)}
        ${mrow('FMI — Fat Mass Index', `${calc.fmi} kg/m²`, fmiNote(calc.fat_risk), C.pink, P)}
        ${mrow('Bone Mineral Content', `${(comp.bmc_g/1000).toFixed(2)} kg`, `${comp.bmc_g > 0 ? ((comp.bmc_g / comp.total_g)*100).toFixed(1) + '% of total mass' : ''}`, C.bone, P)}
        ${mrow('BMI', `${pt.bmi_entered}`, bmiNote(pt.bmi_entered), C.tealLt, P)}
        ${mrow('Total Body Mass (scan)', `${pt.weight_measured_kg} kg`, 'Fat + Lean + BMC', P.gray, P)}
      </div>
      ${bodyFatRefCard(comp.fat_pct, pt.gender, P)}
    </div>
  </div>
</div>`
}

function page2(data: ReportData, P: Pal, lh = false, pageNum = 2, totalPages = 5) {
  const { patient: pt, composition: comp } = data
  const centileBlock = comp.centile !== undefined ? (() => {
    const c = comp.centile!
    const centileColor = c >= 75 ? C.red : c >= 50 ? C.amber : C.greenLt
    const centileLabel = c >= 75 ? 'High — significantly above average for age/sex'
      : c >= 50 ? 'Above average for age and sex'
      : c >= 25 ? 'Below average — favourable'
      : 'Low — well below average for age/sex'
    return `
  <div class="card" ${s('flex-shrink:0')}>
    <div class="sec">Age-Matched Fat Centile</div>
    <div ${s('display:flex;align-items:center;gap:14px')}>
      <div ${s(`font-size:44px;font-weight:800;color:${centileColor};line-height:1`)}>${c}</div>
      <div ${s(`font-size:11px;color:${P.gray};line-height:1.8`)}>
        Body fat higher than ${c}% of same-age, same-sex peers<br>
        <span ${s(`color:${centileColor};font-weight:600`)}>${centileLabel}</span><br>
        <span ${s(`font-size:9.5px`)}>Lower centile = less fat than peers &nbsp;·&nbsp; 50th = average<br>
        Ref: ${esc(pt.ethnicity || 'White')} · USA Lunar v112</span>
      </div>
    </div>
  </div>`
  })() : ''

  return `
<div class="page">
  ${header(pt, 'Fat Distribution Analysis', P, lh, pageNum, totalPages)}
  <div ${s('flex:1;display:flex;gap:16px;min-height:0')}>
    <div ${s('width:160px;flex-shrink:0;display:flex;flex-direction:column')}>
      <img src="${data.images.fat_gradient_url}" alt="fat gradient"
           ${s('width:100%;flex:1;object-fit:contain;border-radius:6px;min-height:0')}>
      <div ${s(`text-align:center;margin-top:6px;font-size:9.5px;color:${P.gray};flex-shrink:0`)}>
        <span ${s('color:#C62828')}>■</span> Dense fat &nbsp;
        <span ${s('color:#1565C0')}>■</span> Low fat
      </div>
    </div>
    <div class="col" ${s('flex:1;gap:14px;min-height:0')}>
      <div class="card" ${s('flex-shrink:0')}>
        <div class="sec">Android / Gynoid Analysis</div>
        ${agChart(comp, pt.gender, P)}
      </div>
      <div class="card" ${s('flex-shrink:0')}>
        <div class="sec">Fat Mass Index (FMI)</div>
        ${fmiScale(data.computed.fmi, pt.gender, P)}
      </div>
      ${centileBlock}
    </div>
  </div>
  <div ${s(`flex-shrink:0;margin-top:8px;border-top:1px solid ${P.border};padding-top:6px;font-size:9px;color:${P.gray};line-height:1.6`)}>
    * Android/Gynoid ratio = android fat% ÷ gynoid fat%, where fat% = fat mass ÷ total regional mass. High lower-body muscle mass <em>lowers</em> gynoid fat% (muscle displaces fat in the ratio denominator), which can <strong ${s(`color:${P.grayLt}`)}>elevate the A/G ratio</strong> even without true abdominal fat excess. Interpret with caution in lean, muscular individuals.
  </div>
</div>`
}

function page3(data: ReportData, P: Pal, lh = false, pageNum = 3, totalPages = 5) {
  const { patient: pt, composition: comp, computed: calc } = data
  const armsLean = comp.regions.Arms ? (comp.regions.Arms.lean_g / 1000).toFixed(2) : '—'
  const legsLean = comp.regions.Legs ? (comp.regions.Legs.lean_g / 1000).toFixed(2) : '—'
  const gynoidNote = comp.regions.Gynoid && comp.regions.Gynoid.lean_pct > 60 ? `
  <div ${s(`margin-top:10px;font-size:10px;color:${P.gray};line-height:1.6;border-top:1px solid ${P.border};padding-top:10px`)}>
    <span ${s(`color:${C.cyan}`)}>Lean ${comp.regions.Gynoid.lean_pct}%</span> of gynoid region is skeletal muscle.
    High lower-body lean mass <strong ${s(`color:${P.text}`)}>lowers gynoid fat%</strong>, which can raise the A/G ratio
    — this may overstate central fat predominance in muscular individuals.
    Assess true abdominal fat from android fat% (${comp.android_fat_pct}%) directly.
  </div>` : ''

  return `
<div class="page">
  ${header(pt, 'Regional Body Composition', P, lh, pageNum, totalPages)}
  <div ${s('flex:1;display:flex;flex-direction:column;gap:14px;min-height:0')}>
    <div class="card" ${s('flex-shrink:0')}>
      <div class="sec">Tissue Breakdown by Region</div>
      <div ${s(`font-size:10px;color:${P.gray};margin-bottom:10px`)}>
        Bar width = proportion of region. &nbsp;
        <span ${s(`color:${C.pink}`)}>■ Fat</span> &nbsp;
        <span ${s(`color:${C.cyan}`)}>■ Lean</span> &nbsp;
        <span ${s(`color:${C.bone}`)}>■ BMC</span>
      </div>
      ${(['Arms', 'Trunk', 'Legs'] as const).map(n => comp.regions[n] ? regionBarRow(n, comp.regions[n]!, P) : '').join('')}
    </div>
    <div class="row" ${s('gap:14px;flex-shrink:0')}>
      <div class="card" ${s('flex:1')}>
        <div class="sec">Android (Abdominal)</div>
        ${comp.regions.Android ? regionDetail(comp.regions.Android, P) : `<div style="color:${P.gray};font-size:11px">No data</div>`}
      </div>
      <div class="card" ${s('flex:1')}>
        <div class="sec">Gynoid (Hip / Thigh)</div>
        ${comp.regions.Gynoid ? regionDetail(comp.regions.Gynoid, P) : `<div style="color:${P.gray};font-size:11px">No data</div>`}
        ${gynoidNote}
      </div>
    </div>
    ${calc.alm_available ? `
    <div class="card" ${s(`background:${P.cardHighlight};border:1px solid ${C.cyan}33;flex-shrink:0`)}>
      <div class="row" ${s('align-items:stretch;gap:0')}>
        <div ${s('flex:1;display:flex;flex-direction:column;padding-right:20px')}>
          <div class="lbl">ALM — Appendicular Lean Mass</div>
          <div ${s(`font-size:40px;font-weight:800;color:${C.cyan};line-height:1;margin-top:14px`)}>${calc.alm_kg}</div>
          <div ${s(`font-size:10px;color:${P.gray};margin-top:4px`)}>kg</div>
          <div ${s(`font-size:9px;color:${P.gray};margin-top:4px`)}>Arms ${armsLean} + Legs ${legsLean} kg</div>
        </div>
        <div ${s(`border-left:1px solid ${P.border};padding-left:20px;flex:1;display:flex;flex-direction:column`)}>
          <div class="lbl">ALMI</div>
          <div ${s(`font-size:40px;font-weight:800;color:${C.cyan};line-height:1;margin-top:14px`)}>${calc.almi}</div>
          <div ${s(`font-size:10px;color:${P.gray};margin-top:4px`)}>kg/m²</div>
          <div ${s('margin-top:8px')}>${almiBadge(calc.almi_rating)}</div>
        </div>
        <div ${s(`border-left:1px solid ${P.border};padding-left:20px;font-size:10px;color:${P.gray};line-height:1.9;max-width:200px;display:flex;flex-direction:column;justify-content:center`)}>
          ${(() => {
            const male = pt.gender.toLowerCase().startsWith('m')
            const lo = male ? 7.26 : 5.67
            const hi = male ? 9.2  : 7.5
            return `
          <div ${s(`font-weight:700;color:${P.text};margin-bottom:4px`)}>ALMI reference (${male ? 'men' : 'women'})</div>
          <div><span ${s(`color:${C.amber}`)}>Low</span> &lt;${lo}</div>
          <div><span ${s(`color:${C.greenLt}`)}>Normal</span> ${lo}–${hi}</div>
          <div><span ${s(`color:${C.cyan}`)}>High</span> &gt;${hi}</div>
          <div ${s(`font-size:9px;color:${P.gray};margin-top:2px`)}>(kg/m²)</div>
          <div ${s(`color:${C.tealLt};font-size:9px;margin-top:6px`)}>Baumgartner 1998 /<br>Cruz-Jentoft criteria</div>`
          })()}
        </div>
      </div>
    </div>
    ${muscleContextCard(P)}` : `
    <div class="card" ${s(`background:${P.cardHighlight};border:1px solid ${P.border};flex-shrink:0`)}>
      <div class="lbl" ${s('margin-bottom:6px')}>ALM / ALMI — Appendicular Lean Mass Index</div>
      <div ${s(`font-size:11px;color:${P.gray};line-height:1.7`)}>
        Regional breakdown was not stored in the MDB analysis for this scan. Arms and Legs lean mass cannot be computed separately,
        so ALM and ALMI are unavailable. ALMI will be available on subsequent scans if regional analysis is retained.
      </div>
    </div>
    ${muscleContextCard(P)}`}
  </div>
</div>`
}

function page4(data: ReportData, P: Pal, lh = false, pageNum = 4, totalPages = 5) {
  const { patient: pt, bone } = data
  const order = ['Head', 'Arms', 'Trunk', 'Legs', 'Ribs', 'Spine', 'Pelvis']

  const regionalEntries = order.filter(n => bone.regions[n])
  const hasRegionalScores = regionalEntries.some(n => bone.regions[n]!.T != null || bone.regions[n]!.Z != null)

  const boneTableRows = regionalEntries.map(n => {
    const d = bone.regions[n]!
    const bmdColor = d.bmd > 1.2 ? C.greenLt : d.bmd > 0.9 ? C.amber : C.red
    const baseRow = `<td style="padding:8px 10px;font-size:11px;color:${P.grayLt};font-weight:600;border-bottom:1px solid ${P.border}">${n}</td>
      <td style="padding:8px 10px;font-size:11px;color:${bmdColor};font-family:monospace;text-align:right;border-bottom:1px solid ${P.border}">${d.bmd.toFixed(3)}</td>`
    if (!hasRegionalScores) return `<tr>${baseRow}</tr>`
    const tSign = d.T != null ? (d.T >= 0 ? '+' : '') : ''
    const zSign = d.Z != null ? (d.Z >= 0 ? '+' : '') : ''
    const tColor = d.T == null ? P.gray : d.T <= -2.5 ? C.red : d.T <= -1 ? C.amber : C.greenLt
    const zColor = d.Z == null ? P.gray : d.Z <= -2 ? C.red : C.greenLt
    return `<tr>${baseRow}
      <td style="padding:8px 10px;font-size:11px;color:${tColor};font-family:monospace;text-align:right;border-bottom:1px solid ${P.border}">${d.T != null ? tSign + d.T.toFixed(1) : '—'}</td>
      <td style="padding:8px 10px;font-size:11px;color:${zColor};font-family:monospace;text-align:right;border-bottom:1px solid ${P.border}">${d.Z != null ? zSign + d.Z.toFixed(1) : '—'}</td>
    </tr>`
  }).join('')

  const scoreCols = hasRegionalScores ? `
    <th style="padding:6px 10px;font-size:10px;font-weight:700;color:${P.gray};text-align:right;text-transform:uppercase;letter-spacing:.5px">T-Score</th>
    <th style="padding:6px 10px;font-size:10px;font-weight:700;color:${P.gray};text-align:right;text-transform:uppercase;letter-spacing:.5px">Z-Score</th>` : ''

  return `
<div class="page">
  ${header(pt, 'Bone Health & Density', P, lh, pageNum, totalPages)}
  <div ${s('flex:1;display:flex;gap:16px;min-height:0')}>
    <div ${s('width:160px;flex-shrink:0;display:flex;flex-direction:column')}>
      <img src="${data.images.bone_url}" alt="bone scan"
           ${s('width:100%;flex:1;object-fit:contain;border-radius:6px;min-height:0')}>
    </div>
    <div class="col" ${s('flex:1;gap:14px;min-height:0')}>
      <div class="card" ${s(`background:${boneCardBg(bone.classification, P)};flex-shrink:0`)}>
        <div class="row" ${s('align-items:stretch;gap:24px;margin-bottom:12px')}>
          <div ${s('display:flex;flex-direction:column')}>
            <div class="lbl">Total Body BMD</div>
            <div ${s(`font-size:9px;color:${P.gray};margin-top:2px`)}>whole-body bone mineral density</div>
            <div ${s('margin-top:6px')}>${boneClassBadge(bone.classification)}</div>
            <div ${s('flex:1;min-height:8px')}></div>
            <div ${s('display:flex;align-items:baseline;gap:4px;margin-top:4px')}>
              <span ${s(`font-size:46px;font-weight:800;color:${boneColor(bone.classification)};line-height:1`)}>${bone.total_bmd.toFixed(3)}</span>
              <span ${s(`font-size:11px;color:${P.gray}`)}>g/cm²</span>
            </div>
          </div>
          ${scoreBlock('T-Score', bone.total_t, 'vs peak bone mass (age 30)', P)}
          ${scoreBlock('Z-Score', bone.total_z, 'vs same age &amp; sex peers', P)}
        </div>
        ${whoViz(bone.total_t, P)}
      </div>
      <div class="card" ${s('flex-shrink:0')}>
        <div class="sec">Understanding Your Scores</div>
        <div class="row" ${s('gap:14px;margin-top:4px')}>
          <div ${s(`flex:1;background:${P.bg};border-radius:6px;padding:12px 14px`)}>
            <div ${s(`font-size:11px;font-weight:700;color:${C.tealLt};margin-bottom:8px`)}>T-Score</div>
            <div ${s(`font-size:10.5px;color:${P.gray};line-height:1.7`)}>
              Compares your bone density to a healthy <strong>30-year-old</strong> of the same sex.
              This is the WHO standard for diagnosing bone loss.<br><br>
              <span ${s(`color:${C.greenLt}`)}>≥ −1.0 Normal</span> ·
              <span ${s(`color:${C.amber}`)}> −1 to −2.5 Osteopenia</span> ·
              <span ${s(`color:${C.red}`)}> ≤ −2.5 Osteoporosis</span>
            </div>
          </div>
          <div ${s(`flex:1;background:${P.bg};border-radius:6px;padding:12px 14px`)}>
            <div ${s(`font-size:11px;font-weight:700;color:${C.tealLt};margin-bottom:8px`)}>Z-Score</div>
            <div ${s(`font-size:10.5px;color:${P.gray};line-height:1.7`)}>
              Compares your bone density to <strong>people your own age</strong> and sex.
              A Z-score below −2.0 = "below expected range for age."<br><br>
              If T is low but Z is near 0, bone loss is age-related, not accelerated.
            </div>
          </div>
        </div>
      </div>
      <div class="card" ${s('flex-shrink:0')}>
        <div class="sec">BMD by Body Region</div>
        <table style="width:100%;border-collapse:collapse">
          <thead>
            <tr style="border-bottom:1px solid ${P.border}">
              <th style="padding:6px 10px;font-size:10px;font-weight:700;color:${P.gray};text-align:left;text-transform:uppercase;letter-spacing:.5px">Region</th>
              <th style="padding:6px 10px;font-size:10px;font-weight:700;color:${P.gray};text-align:right;text-transform:uppercase;letter-spacing:.5px">BMD (g/cm²)</th>
              ${scoreCols}
            </tr>
          </thead>
          <tbody>${boneTableRows}</tbody>
        </table>
        <div style="font-size:9px;color:${P.gray};margin-top:7px">
          BMD colour: <span style="color:${C.greenLt}">■</span> &gt;1.2 · <span style="color:${C.amber}">■</span> 0.9–1.2 · <span style="color:${C.red}">■</span> &lt;0.9 g/cm² &nbsp;·&nbsp;
          ${hasRegionalScores ? 'T/Z scores shown where computed by scanner' : 'T-score and Z-score available for Total Body only (shown above)'}
        </div>
      </div>
      ${boneGuideCard(bone.classification, P)}
    </div>
  </div>
</div>`
}

function page5(data: ReportData, P: Pal, lh = false, pageNum = 5, totalPages = 5) {
  const { patient: pt, composition: comp, computed: calc, bone } = data
  const items = summaryItems(comp, calc, bone, pt.gender)
  const statusStyle = (st: string) => ({
    good:  { bg: P.statusGood,  border: C.greenLt },
    warn:  { bg: P.statusWarn,  border: C.amber   },
    alert: { bg: P.statusAlert, border: C.red     },
    info:  { bg: P.statusInfo,  border: C.tealLt  },
  }[st] ?? { bg: P.card, border: P.border })

  const cards = items.map(item => {
    const st = statusStyle(item.status)
    return `
    <div ${s(`background:${st.bg};border:1px solid ${st.border}40;border-left:4px solid ${st.border};border-radius:6px;padding:14px 18px;display:flex;flex-direction:column;justify-content:center`)}>
      <div ${s(`font-size:13px;font-weight:700;color:${st.border};margin-bottom:6px`)}>${item.title}</div>
      <div ${s(`font-size:11px;color:${P.grayLt};line-height:1.65`)}>${item.body}</div>
    </div>`
  }).join('')

  return `
<div class="page">
  ${header(pt, 'Clinical Summary', P, lh, pageNum, totalPages)}
  <div ${s('flex:1;display:grid;grid-template-columns:1fr 1fr;grid-auto-rows:auto;align-content:start;gap:12px;min-height:0')}>
    ${cards}
  </div>
  <div class="page-footer" ${s(`flex-shrink:0;margin-top:10px;border-top:1px solid ${P.border};padding-top:7px;font-size:9px;color:${P.gray};line-height:1.7`)}>
    <div>
      Reference population: <strong>${esc(pt.ethnicity || 'White')}</strong> (GE Lunar normative database).
      South Asian-specific T &amp; Z score references are not available on this scanner platform — results are benchmarked against the White/Caucasian normative population, which may underestimate bone loss risk in South Asian individuals.
    </div>
    <div ${s('margin-top:3px')}>
      Visceral fat (VAT) estimation is not available on this scanner platform (GE Lunar DPX-NT). VAT requires dedicated hardware such as GE iDXA or abdominal CT.
      Trend comparison will be available after repeat scans on the same scanner.
    </div>
    <div ${s('margin-top:3px')}>
      Generated by SDRC DEXA Report System · Scanner ${esc(pt.scanner)} · ${esc(pt.software)} ·
      Scan ${esc(pt.scan_date)} · Bone: WHO criteria · ALM/FMI: NHANES/FNIH standards · For clinical use only — interpret with a qualified clinician.
    </div>
  </div>
</div>`
}

/* ── Clinical summary items ──────────────────────────────────────────────── */
function summaryItems(
  comp: ReportData['composition'],
  calc: ReportData['computed'],
  bone: ReportData['bone'],
  gender: string,
) {
  type Item = { title: string; body: string; status: string }
  const out: Item[] = []
  const male = gender.toLowerCase().startsWith('m')

  // ACE body fat % categories — gender-specific
  const [athHi, fitHi, normHi] = male ? [14, 18, 25] : [21, 25, 32]
  if (comp.fat_pct < athHi) out.push({ status:'good', title:'Body Fat: Athletic',
    body:`${comp.fat_pct}% — excellent. Well within the athletic range for ${male ? 'men' : 'women'} (ACE: &lt;${athHi}%).` })
  else if (comp.fat_pct < fitHi) out.push({ status:'good', title:'Body Fat: Fit',
    body:`${comp.fat_pct}% — healthy fit range for ${male ? 'men' : 'women'} (ACE: ${athHi}–${fitHi}%).` })
  else if (comp.fat_pct < normHi) out.push({ status:'warn', title:'Body Fat: Normal Range',
    body:`${comp.fat_pct}% — normal but not optimal (ACE: ${fitHi}–${normHi}% for ${male ? 'men' : 'women'}). Lifestyle optimisation (activity + dietary balance) is advised.` })
  else out.push({ status:'warn', title:'Body Fat: Above Target Range',
    body:`${comp.fat_pct}% — above the healthy range for ${male ? 'men' : 'women'} (ACE &gt;${normHi}%). Gradual reduction through consistent activity and dietary habits is recommended.` })

  if (comp.ag_ratio < 0.8) out.push({ status:'good', title:'Fat Distribution: Gynoid-Dominant',
    body:`A/G ${comp.ag_ratio} — fat stored preferentially in the lower body. Favourable metabolic profile.` })
  else if (comp.ag_ratio < 1.0) out.push({ status:'info', title:'Fat Distribution: Mild Central Tendency',
    body:`A/G ${comp.ag_ratio} — mild central fat predominance. Focus on reducing abdominal fat through aerobic activity. Monitor over time.` })
  else if (calc.alm_available && calc.almi_rating === 'high') out.push({ status:'info', title:'Fat Distribution: Muscular Context',
    body:`A/G ${comp.ag_ratio} — mild central pattern. With ALMI ${calc.almi} kg/m² (high muscle mass), the gynoid region is muscle-dominant (${comp.regions.Gynoid?.lean_pct ?? '—'}% lean). Monitor android fat% (${comp.android_fat_pct}%) as the meaningful indicator.` })
  else out.push({ status:'warn', title:'Fat Distribution: Central Fat Predominance',
    body:`A/G ${comp.ag_ratio} — android (abdominal) fat pattern. Lifestyle optimisation targeting abdominal fat is advised. Reassess after 3–6 months of intervention.` })

  const almiLo = male ? 7.26 : 5.67
  if (!calc.alm_available) {
    out.push({ status:'info', title:'Muscle Mass (ALMI): Data Unavailable',
      body:`Regional MDB analysis was not stored for this scan. ALM and ALMI cannot be computed. Ensure regional body-composition data is saved at time of analysis for future scans.` })
  } else if (calc.almi_rating === 'high') out.push({ status:'good', title:'Muscle Mass: Excellent',
    body:`ALMI ${calc.almi} kg/m² — above-average appendicular lean mass. Well above the ${male ? 'male' : 'female'} sarcopenia threshold (${almiLo} kg/m²).` })
  else if (calc.almi_rating === 'normal') out.push({ status:'good', title:'Muscle Mass: Normal',
    body:`ALMI ${calc.almi} kg/m² — within normal reference range for ${male ? 'men' : 'women'}. Maintain with regular resistance training.` })
  else out.push({ status:'warn', title:'Muscle Mass: Below Reference',
    body:`ALMI ${calc.almi} kg/m² — below the ${male ? 'male' : 'female'} sarcopenia threshold (${almiLo} kg/m²). Progressive resistance training and adequate protein (≥1.6 g/kg/day) recommended.` })

  if (calc.fat_risk === 'low') out.push({ status:'good', title:'Fat Mass Index: Normal',
    body:`FMI ${calc.fmi} kg/m² — normal range. More precise than BMI as it reflects actual fat mass independent of muscle.` })
  else if (calc.fat_risk === 'moderate') out.push({ status:'info', title:'Fat Mass Index: Mildly Elevated',
    body:`FMI ${calc.fmi} kg/m² — mildly above target (&lt;6 men / &lt;9 women kg/m²). Lifestyle optimisation advised. Monitor at next scan.` })
  else out.push({ status:'warn', title:'Fat Mass Index: Above Target Range',
    body:`FMI ${calc.fmi} kg/m² — above target range. Unlike BMI, FMI is not affected by muscle mass — this reflects actual fat burden. Intervention recommended.` })

  if (bone.classification === 'normal') out.push({ status:'good', title:'Bone Density: Normal',
    body:`BMD ${bone.total_bmd.toFixed(3)} g/cm², T-score ${bone.total_t >= 0 ? '+' : ''}${bone.total_t.toFixed(1)} — bone density is within the normal range.` })
  else if (bone.classification === 'low_mass') out.push({ status:'warn', title:'Bone Density: Osteopenia',
    body:`T-score ${bone.total_t.toFixed(1)} — mildly below peak bone mass. Ensure adequate calcium (1000–1200 mg/day), vitamin D, and weight-bearing activity. Review at next scan.` })
  else out.push({ status:'warn', title:'Bone Density: Osteoporosis Range',
    body:`T-score ${bone.total_t.toFixed(1)} — clinical correlation and FRAX fracture risk assessment recommended. Please discuss with your clinician.` })

  return out
}
