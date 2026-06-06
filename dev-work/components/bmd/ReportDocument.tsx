/**
 * Pure React component — rendered to static HTML via renderToStaticMarkup.
 * No hooks, no client-side JS. Safe to use in a route handler.
 */
import type { ReportData, RegionComposition } from '../../lib/bmd-types'

const C = {
  bg: '#0D1B2A', card: '#0f2235', border: '#1a3a55',
  teal: '#0D7377', tealLt: '#14a8ae',
  pink: '#E91E8C', cyan: '#00BCD4', bone: '#B0BEC5',
  green: '#2E7D32', greenLt: '#4CAF50',
  amber: '#E65100', red: '#B71C1C',
  white: '#FFFFFF', gray: '#9E9E9E', grayLt: '#CFD8DC',
}

export default function ReportDocument({ data }: { data: ReportData }) {
  const { patient: pt, composition: comp, computed: calc, bone } = data

  return (
    <html lang="en">
      <head>
        <meta charSet="utf-8" />
        <title>DEXA Report — {pt.name}</title>
        <style dangerouslySetInnerHTML={{ __html: `
          @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');
          *{box-sizing:border-box;margin:0;padding:0}
          body{background:${C.bg};font-family:'Inter',sans-serif;color:${C.white};
               -webkit-print-color-adjust:exact;print-color-adjust:exact}
          .page{width:210mm;min-height:297mm;padding:10mm 12mm;margin:0 auto;
                background:${C.bg};page-break-after:always;position:relative}
          .page:last-child{page-break-after:auto}
          @page{size:A4;margin:0}
          .row{display:flex;gap:12px}
          .col{display:flex;flex-direction:column}
          .card{background:${C.card};border:1px solid ${C.border};border-radius:8px;padding:12px}
          .lbl{font-size:9px;font-weight:600;text-transform:uppercase;letter-spacing:.8px;color:${C.gray}}
          .sec{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:${C.tealLt};margin-bottom:8px}
          .tag{display:inline-block;padding:2px 8px;border-radius:3px;font-size:9px;font-weight:700;
               text-transform:uppercase;letter-spacing:.5px}
          hr{border:none;border-top:1px solid ${C.border};margin:8px 0}
          /* Print: switch to white */
          @media print{
            body,html,.page{background:#fff!important;color:#111!important}
            .card{background:#f8f8f8!important;border-color:#ddd!important}
          }
        ` }} />
      </head>
      <body>
        <Page1 data={data} />
        <Page2 data={data} />
        <Page3 data={data} />
        <Page4 data={data} />
        <Page5 data={data} />
      </body>
    </html>
  )
}

// ── Shared: Page header ───────────────────────────────────────────────────────

function PageHeader({ pt, title }: { pt: ReportData['patient']; title: string }) {
  const ethnicityNote = pt.ethnicity
    ? ` · Reference: ${pt.ethnicity}`
    : ''
  return (
    <div style={{ borderBottom: `2px solid ${C.teal}`, paddingBottom: 7, marginBottom: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <div style={{ fontSize: 8, color: C.teal, fontWeight: 700, letterSpacing: 2, textTransform: 'uppercase' }}>
            SDRC Diagnostics · DEXA Body Composition
          </div>
          <div style={{ fontSize: 15, fontWeight: 800, color: C.white, marginTop: 1 }}>{title}</div>
        </div>
        <div style={{ textAlign: 'right', fontSize: 8, color: C.gray, lineHeight: 1.7 }}>
          <div style={{ color: C.white, fontWeight: 700, fontSize: 9 }}>{pt.name}</div>
          <div>{pt.gender} · {pt.age}y · {pt.height_cm} cm · {pt.weight_entered_kg} kg</div>
          <div>Scan: {pt.scan_date} {pt.scan_time}</div>
          <div style={{ color: C.tealLt }}>Ethnicity: {pt.ethnicity || 'White'}{ethnicityNote ? '' : ' (default)'}</div>
        </div>
      </div>
    </div>
  )
}

// ── PAGE 1: Body Composition Summary ─────────────────────────────────────────

function Page1({ data }: { data: ReportData }) {
  const { patient: pt, composition: comp, computed: calc } = data
  const fatKg   = (comp.fat_g  / 1000).toFixed(1)
  const leanKg  = (comp.lean_g / 1000).toFixed(1)
  const boneKg  = (comp.bmc_g  / 1000).toFixed(2)

  return (
    <div className="page">
      <PageHeader pt={pt} title="Body Composition Summary" />

      <div className="row" style={{ gap: 14, alignItems: 'flex-start' }}>
        {/* Silhouette */}
        <div style={{ width: 125, flexShrink: 0 }}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={data.images.fat_lean_url} alt="Body silhouette"
            style={{ width: '100%', borderRadius: 6 }} />
          <div style={{ textAlign: 'center', marginTop: 4, fontSize: 7.5, color: C.gray }}>
            <span style={{ color: C.pink }}>■</span> Fat &nbsp;
            <span style={{ color: C.cyan }}>■</span> Lean &nbsp;
            <span style={{ color: C.bone }}>■</span> Bone
          </div>
        </div>

        <div className="col" style={{ flex: 1, gap: 10 }}>
          {/* Top metric row */}
          <div className="row" style={{ gap: 8 }}>
            {[
              { lbl: 'Body Fat %',  val: `${comp.fat_pct}%`,  color: C.pink,    sub: comp.centile ? `Centile ${comp.centile}` : undefined },
              { lbl: 'Fat Mass',    val: `${fatKg} kg`,        color: C.pink    },
              { lbl: 'Lean Mass',   val: `${leanKg} kg`,       color: C.cyan    },
              { lbl: 'Bone (BMC)',  val: `${boneKg} kg`,       color: C.bone    },
            ].map(m => (
              <div key={m.lbl} className="card" style={{ flex: 1 }}>
                <div className="lbl">{m.lbl}</div>
                <div style={{ fontSize: 18, fontWeight: 800, color: m.color, marginTop: 2, lineHeight: 1 }}>{m.val}</div>
                {m.sub && <div style={{ fontSize: 7.5, color: C.gray, marginTop: 2 }}>{m.sub}</div>}
              </div>
            ))}
          </div>

          {/* Composition bar */}
          <div className="card">
            <div className="sec">Body Composition</div>
            <CompBar fat={comp.fat_g} lean={comp.lean_g} bone={comp.bmc_g} />
          </div>

          {/* Performance metrics */}
          <div className="card">
            <div className="sec">Performance &amp; Metabolic Metrics</div>
            <div className="row" style={{ gap: 12 }}>
              <div style={{ flex: 1 }}>
                <MRow lbl="ALM — Appendicular Lean"
                  val={`${calc.alm_kg} kg`}
                  note="Arms + Legs lean mass"
                  color={C.cyan} />
                <MRow lbl="ALMI — Lean Mass Index"
                  val={`${calc.almi} kg/m²`}
                  note={almiNote(calc.almi_rating)}
                  color={C.cyan} />
                <MRow lbl="FMI — Fat Mass Index"
                  val={`${calc.fmi} kg/m²`}
                  note={fmiNote(calc.fat_risk, pt.gender)}
                  color={C.pink} />
              </div>
              <div style={{ flex: 1 }}>
                <MRow lbl="BMI"
                  val={`${pt.bmi_entered}`}
                  note={bmiNote(pt.bmi_entered)}
                  color={C.tealLt} />
                <MRow lbl="Resting Metabolic Rate"
                  val={`${calc.rmr_kcal.toLocaleString()} kcal/day`}
                  note="Katch-McArdle formula (lean mass based)"
                  color={C.tealLt} />
                <MRow lbl="Total Body Mass (scan)"
                  val={`${data.patient.weight_measured_kg} kg`}
                  note="Fat + Lean + Bone measured by scan"
                  color={C.gray} />
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── PAGE 2: Fat Distribution ──────────────────────────────────────────────────

function Page2({ data }: { data: ReportData }) {
  const { patient: pt, composition: comp, computed: calc } = data
  return (
    <div className="page">
      <PageHeader pt={pt} title="Fat Distribution Analysis" />

      <div className="row" style={{ gap: 14, alignItems: 'flex-start' }}>
        {/* Fat gradient image */}
        <div style={{ width: 125, flexShrink: 0 }}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={data.images.fat_gradient_url} alt="Fat gradient"
            style={{ width: '100%', borderRadius: 6 }} />
          <div style={{ textAlign: 'center', marginTop: 4, fontSize: 7.5, color: C.gray }}>
            <span style={{ color: '#C62828' }}>■</span> Dense fat &nbsp;
            <span style={{ color: '#1565C0' }}>■</span> Low fat
          </div>
        </div>

        <div className="col" style={{ flex: 1, gap: 12 }}>
          {/* A/G Analysis */}
          <div className="card">
            <div className="sec">Android / Gynoid Analysis</div>
            <AGChart comp={comp} />
          </div>

          {/* FMI Scale */}
          <div className="card">
            <div className="sec">Fat Mass Index (FMI)</div>
            <FmiScale fmi={calc.fmi} gender={pt.gender} />
          </div>

          {/* Centile */}
          {comp.centile !== undefined && (
            <div className="card" style={{ padding: '8px 12px' }}>
              <div className="sec">Age-Matched Fat Centile</div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <div style={{ fontSize: 30, fontWeight: 800,
                  color: comp.centile > 75 ? C.amber : C.greenLt }}>
                  {comp.centile}
                </div>
                <div style={{ fontSize: 8.5, color: C.gray, lineHeight: 1.5 }}>
                  Body fat is higher than {comp.centile}% of<br />
                  same-age, same-sex reference population<br />
                  <span style={{ color: C.tealLt, fontSize: 7.5 }}>
                    Reference: {pt.ethnicity || 'White'} · USA Lunar v112
                  </span>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ── PAGE 3: Regional Body Composition ────────────────────────────────────────

function Page3({ data }: { data: ReportData }) {
  const { patient: pt, composition: comp, computed: calc } = data
  return (
    <div className="page">
      <PageHeader pt={pt} title="Regional Body Composition" />

      <div className="card" style={{ marginBottom: 12 }}>
        <div className="sec">Tissue Breakdown by Region</div>
        <div style={{ fontSize: 8, color: C.gray, marginBottom: 8 }}>
          Bar width = proportion of region. &nbsp;
          <span style={{ color: C.pink }}>■ Fat</span> &nbsp;
          <span style={{ color: C.cyan }}>■ Lean</span> &nbsp;
          <span style={{ color: C.bone }}>■ Bone</span>
        </div>
        {(['Arms', 'Trunk', 'Legs'] as const).map(region => {
          const r = comp.regions[region]
          if (!r) return null
          return <RegionBarRow key={region} name={region} d={r} />
        })}
      </div>

      <div className="row" style={{ gap: 12, marginBottom: 12 }}>
        {/* Android detail */}
        <div className="card" style={{ flex: 1 }}>
          <div className="sec">Android (Abdominal)</div>
          {comp.regions.Android && <RegionDetail d={comp.regions.Android} />}
        </div>
        {/* Gynoid detail */}
        <div className="card" style={{ flex: 1 }}>
          <div className="sec">Gynoid (Hip / Thigh)</div>
          {comp.regions.Gynoid && <RegionDetail d={comp.regions.Gynoid} />}
          {comp.regions.Gynoid && comp.regions.Gynoid.lean_pct > 60 && (
            <div style={{ marginTop: 8, fontSize: 7.5, color: C.gray, lineHeight: 1.5,
              borderTop: `1px solid ${C.border}`, paddingTop: 7 }}>
              <span style={{ color: C.cyan }}>Lean {comp.regions.Gynoid.lean_pct}%</span> of gynoid
              region is muscle. For active individuals, higher gynoid mass typically reflects
              <strong style={{ color: C.white }}> leg musculature</strong>, not excess fat.
              Assess metabolic risk from the fat% alone, not total regional weight.
            </div>
          )}
        </div>
      </div>

      {/* ALM highlight */}
      <div className="card" style={{ background: '#0a1f30', border: `1px solid ${C.cyan}33` }}>
        <div className="row" style={{ alignItems: 'center', gap: 20 }}>
          <div>
            <div className="lbl">ALM — Appendicular Lean Mass</div>
            <div style={{ fontSize: 30, fontWeight: 800, color: C.cyan, lineHeight: 1, marginTop: 2 }}>
              {calc.alm_kg} kg
            </div>
            <div style={{ fontSize: 8, color: C.gray, marginTop: 3 }}>
              Arms lean {comp.regions.Arms ? (comp.regions.Arms.lean_g / 1000).toFixed(2) : '—'} kg
              + Legs lean {comp.regions.Legs ? (comp.regions.Legs.lean_g / 1000).toFixed(2) : '—'} kg
            </div>
          </div>
          <div style={{ borderLeft: `1px solid ${C.border}`, paddingLeft: 20 }}>
            <div className="lbl">ALMI</div>
            <div style={{ fontSize: 30, fontWeight: 800, color: C.cyan, lineHeight: 1, marginTop: 2 }}>
              {calc.almi}
              <span style={{ fontSize: 11, fontWeight: 400, color: C.gray }}> kg/m²</span>
            </div>
            <div style={{ marginTop: 4 }}>
              <AlmiBadge rating={calc.almi_rating} />
            </div>
          </div>
          <div style={{ borderLeft: `1px solid ${C.border}`, paddingLeft: 20,
            fontSize: 8, color: C.gray, lineHeight: 1.7, maxWidth: 200 }}>
            <strong style={{ color: C.white }}>ALMI reference (men):</strong><br />
            Low &lt; 7.26 · Normal 7.26–9.2 · High &gt; 9.2 kg/m²<br />
            <span style={{ color: C.tealLt, fontSize: 7.5 }}>
              Source: Baumgartner 1998 / Cruz-Jentoft sarcopenia criteria
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── PAGE 4: Bone Health ───────────────────────────────────────────────────────

function Page4({ data }: { data: ReportData }) {
  const { patient: pt, bone } = data
  return (
    <div className="page">
      <PageHeader pt={pt} title="Bone Health &amp; Density" />

      <div className="row" style={{ gap: 14, alignItems: 'flex-start' }}>
        {/* Bone image */}
        <div style={{ width: 125, flexShrink: 0 }}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={data.images.bone_url} alt="Bone scan"
            style={{ width: '100%', borderRadius: 6 }} />
        </div>

        <div className="col" style={{ flex: 1, gap: 12 }}>
          {/* Total BMD hero */}
          <div className="card" style={{ background: boneCardBg(bone.classification) }}>
            <div className="row" style={{ alignItems: 'center', gap: 20, marginBottom: 10 }}>
              <div>
                <div className="lbl">Total Body BMD</div>
                <div style={{ fontSize: 34, fontWeight: 800, color: boneColor(bone.classification), lineHeight: 1 }}>
                  {bone.total_bmd.toFixed(3)}
                  <span style={{ fontSize: 11, fontWeight: 400, color: C.gray }}> g/cm²</span>
                </div>
              </div>
              <ScoreBlock label="T-Score" value={bone.total_t}
                meaning="vs peak bone mass (age 30)" />
              <ScoreBlock label="Z-Score" value={bone.total_z}
                meaning="vs same age &amp; sex peers" />
              <BoneClassBadge cls={bone.classification} />
            </div>

            {/* WHO T-score bar */}
            <WHO_TScoreViz t={bone.total_t} />
          </div>

          {/* T / Z score explanations */}
          <div className="card">
            <div className="sec">Understanding Your Scores</div>
            <div className="row" style={{ gap: 12, marginTop: 4 }}>
              <ScoreExplain title="T-Score" color={C.tealLt}>
                Compares your bone density to a healthy <strong>30-year-old</strong> of the same sex.
                This is the WHO standard for diagnosing bone loss.
                <br />
                <span style={{ color: C.greenLt }}>≥ −1.0 Normal</span> ·{' '}
                <span style={{ color: C.amber }}>−1 to −2.5 Osteopenia</span> ·{' '}
                <span style={{ color: C.red }}>≤ −2.5 Osteoporosis</span>
              </ScoreExplain>
              <ScoreExplain title="Z-Score" color={C.tealLt}>
                Compares your bone density to <strong>people your own age</strong> and sex.
                A Z-score below −2.0 means "below expected range for age."
                <br />
                If T is low but Z is normal, bone loss is age-related (not accelerated).
                If both are low, further investigation is warranted.
              </ScoreExplain>
            </div>
          </div>

          {/* Regional BMD — only non-Total rows have BMD, Total has T/Z */}
          <div className="card">
            <div className="sec">BMD by Body Region</div>
            <BoneRegionBars regions={bone.regions} />
          </div>
        </div>
      </div>
    </div>
  )
}

// ── PAGE 5: Clinical Summary ──────────────────────────────────────────────────

function Page5({ data }: { data: ReportData }) {
  const { patient: pt, composition: comp, computed: calc, bone } = data
  const items = buildSummaryItems(comp, calc, bone)

  return (
    <div className="page">
      <PageHeader pt={pt} title="Clinical Summary" />

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginTop: 4 }}>
        {items.map((item) => {
          const c = statusStyle(item.status)
          return (
            <div key={item.title} style={{
              background: c.bg,
              border: `1px solid ${c.border}40`,
              borderLeft: `3px solid ${c.border}`,
              borderRadius: 6, padding: '8px 12px',
            }}>
              <div style={{ fontSize: 9.5, fontWeight: 700, color: c.border, marginBottom: 3 }}>
                {item.title}
              </div>
              <div style={{ fontSize: 8.5, color: C.grayLt, lineHeight: 1.55 }}
                dangerouslySetInnerHTML={{ __html: item.body }} />
            </div>
          )
        })}
      </div>

      {/* Footer */}
      <div style={{ position: 'absolute', bottom: 10, left: 12, right: 12,
        borderTop: `1px solid ${C.border}`, paddingTop: 6,
        fontSize: 7, color: C.gray, lineHeight: 1.5 }}>
        Generated by SDRC DEXA Report System · Scanner {pt.scanner} · {pt.software} ·
        Scan {pt.scan_date} · Reference population: {pt.ethnicity || 'White'} ·
        Bone norms per WHO criteria · ALM/FMI per NHANES / FNIH standards.
        This report is for clinical use only and should be interpreted by a qualified clinician.
      </div>
    </div>
  )
}

// ── Shared sub-components ─────────────────────────────────────────────────────

function CompBar({ fat, lean, bone }: { fat: number; lean: number; bone: number }) {
  const t = fat + lean + bone
  const fp = (fat  / t * 100).toFixed(1)
  const lp = (lean / t * 100).toFixed(1)
  const bp = (bone / t * 100).toFixed(1)
  return (
    <div>
      <div style={{ display: 'flex', height: 18, borderRadius: 4, overflow: 'hidden', marginBottom: 5 }}>
        <div style={{ width: `${fp}%`, background: C.pink }} />
        <div style={{ width: `${lp}%`, background: C.cyan }} />
        <div style={{ width: `${bp}%`, background: C.bone }} />
      </div>
      <div style={{ display: 'flex', fontSize: 8, color: C.gray, justifyContent: 'space-between' }}>
        <span><span style={{ color: C.pink }}>■</span> Fat {fp}% ({(fat/1000).toFixed(1)} kg)</span>
        <span><span style={{ color: C.cyan }}>■</span> Lean {lp}% ({(lean/1000).toFixed(1)} kg)</span>
        <span><span style={{ color: C.bone }}>■</span> Bone {bp}% ({(bone/1000).toFixed(2)} kg)</span>
      </div>
    </div>
  )
}

function MRow({ lbl, val, note, color }: { lbl: string; val: string; note?: string; color: string }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline',
      padding: '4px 0', borderBottom: `1px solid ${C.border}` }}>
      <div style={{ fontSize: 8.5, color: C.gray }}>{lbl}</div>
      <div style={{ textAlign: 'right' }}>
        <div style={{ fontSize: 11, fontWeight: 700, color }}>{val}</div>
        {note && <div style={{ fontSize: 7.5, color: C.gray }}>{note}</div>}
      </div>
    </div>
  )
}

function AGChart({ comp }: { comp: ReportData['composition'] }) {
  const android = comp.regions.Android
  const gynoid  = comp.regions.Gynoid
  const agColor = comp.ag_ratio < 0.8 ? C.greenLt : comp.ag_ratio < 1.0 ? C.amber : C.red
  const riskLabel = comp.ag_ratio < 0.8 ? 'Low Risk' : comp.ag_ratio < 1.0 ? 'Moderate' : 'Elevated'

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 10 }}>
        <div>
          <div className="lbl">A/G Fat % Ratio</div>
          <div style={{ fontSize: 28, fontWeight: 800, color: agColor, lineHeight: 1 }}>
            {comp.ag_ratio}
          </div>
          <span className="tag" style={{ color: agColor, background: agColor + '22',
            border: `1px solid ${agColor}44`, marginTop: 3, display: 'inline-block' }}>
            {riskLabel}
          </span>
        </div>
        <div style={{ fontSize: 8, color: C.gray, lineHeight: 1.7, background: C.bg,
          borderRadius: 6, padding: '6px 10px', maxWidth: 220 }}>
          <span style={{ color: C.greenLt, fontWeight: 700 }}>&lt; 0.80 Low risk</span> ·{' '}
          <span style={{ color: C.amber, fontWeight: 700 }}>0.80–1.0 Moderate</span> ·{' '}
          <span style={{ color: C.red, fontWeight: 700 }}>&gt; 1.0 Elevated</span><br />
          Ratio uses <strong style={{ color: C.white }}>fat % only</strong> — not total regional mass.
          Muscular legs do not inflate this ratio.
        </div>
      </div>

      {/* Side-by-side stacked bars */}
      {android && gynoid && (
        <div style={{ display: 'flex', gap: 10 }}>
          {[
            { name: 'Android (Abdominal)', d: android, fatPct: comp.android_fat_pct },
            { name: 'Gynoid (Hip / Thigh)',  d: gynoid,  fatPct: comp.gynoid_fat_pct  },
          ].map(({ name, d, fatPct }) => (
            <div key={name} style={{ flex: 1 }}>
              <div style={{ fontSize: 8.5, fontWeight: 600, color: C.grayLt, marginBottom: 4 }}>{name}</div>
              <div style={{ display: 'flex', height: 22, borderRadius: 3, overflow: 'hidden' }}>
                <div style={{ width: `${d.fat_pct}%`, background: C.pink, display: 'flex',
                  alignItems: 'center', justifyContent: 'center' }}>
                  {d.fat_pct > 12 && <span style={{ fontSize: 7, fontWeight: 700, color: '#fff' }}>{d.fat_pct}%</span>}
                </div>
                <div style={{ width: `${d.lean_pct}%`, background: C.cyan, display: 'flex',
                  alignItems: 'center', justifyContent: 'center' }}>
                  {d.lean_pct > 12 && <span style={{ fontSize: 7, fontWeight: 700, color: C.bg }}>{d.lean_pct}%</span>}
                </div>
                <div style={{ width: `${d.bone_pct}%`, background: C.bone }} />
              </div>
              <div style={{ fontSize: 7.5, color: C.gray, marginTop: 4, lineHeight: 1.8 }}>
                <div><span style={{ color: C.pink }}>■</span> Fat: {fatPct}% · {(d.fat_g/1000).toFixed(2)} kg</div>
                <div><span style={{ color: C.cyan }}>■</span> Lean: {d.lean_pct}% · {(d.lean_g/1000).toFixed(2)} kg</div>
                <div style={{ color: d.lean_pct > 60 ? C.cyan : C.gray, fontWeight: d.lean_pct > 60 ? 600 : 400 }}>
                  {d.lean_pct > 60 ? 'Muscle-dominant ✓' : 'Mixed composition'}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function FmiScale({ fmi, gender }: { fmi: number; gender: string }) {
  const male  = gender.toLowerCase().startsWith('m')
  const max   = male ? 15 : 18
  const zones = male
    ? [{ pct: 40,   label: 'Normal < 6',   color: C.green },
       { pct: 20,   label: 'Elevated 6–9', color: C.amber },
       { pct: 40,   label: 'Obese > 9',    color: C.red   }]
    : [{ pct: 50,   label: 'Normal < 9',   color: C.green },
       { pct: 22.2, label: 'Elevated 9–13',color: C.amber },
       { pct: 27.8, label: 'Obese > 13',   color: C.red   }]
  const markerPct = Math.min(fmi / max * 100, 99)
  const col = fmiColor(fmi, male)
  return (
    <div>
      <div style={{ position: 'relative', height: 14, borderRadius: 4, overflow: 'visible',
        display: 'flex', marginBottom: 6 }}>
        <div style={{ display: 'flex', width: '100%', borderRadius: 4, overflow: 'hidden' }}>
          {zones.map(z => <div key={z.label} style={{ width: `${z.pct}%`, background: z.color }} />)}
        </div>
        <div style={{ position: 'absolute', left: `${markerPct}%`, top: -3, bottom: -3,
          width: 3, background: C.white, borderRadius: 2, transform: 'translateX(-50%)' }} />
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 7, color: C.gray, marginBottom: 5 }}>
        {zones.map(z => <span key={z.label}>{z.label}</span>)}
      </div>
      <div style={{ fontSize: 11, fontWeight: 700, color: col }}>
        Your FMI: {fmi} kg/m²
        <span style={{ fontSize: 8, fontWeight: 400, color: C.gray, marginLeft: 6 }}>
          (fat kg ÷ height m²)
        </span>
      </div>
    </div>
  )
}

function RegionBarRow({ name, d }: { name: string; d: RegionComposition }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
      <div style={{ width: 36, fontSize: 8.5, fontWeight: 600, color: C.grayLt }}>{name}</div>
      <div style={{ flex: 1, display: 'flex', height: 16, borderRadius: 3, overflow: 'hidden' }}>
        <div style={{ width: `${d.fat_pct}%`,  background: C.pink }} />
        <div style={{ width: `${d.lean_pct}%`, background: C.cyan }} />
        <div style={{ width: `${d.bone_pct}%`, background: C.bone }} />
      </div>
      <div style={{ fontSize: 7.5, color: C.gray, minWidth: 160, textAlign: 'right' }}>
        <span style={{ color: C.pink }}>F {d.fat_pct}%</span> ·{' '}
        <span style={{ color: C.cyan }}>L {d.lean_pct}%</span> ·{' '}
        <span style={{ color: C.bone }}>B {d.bone_pct}%</span>
        <span style={{ color: C.gray }}> ({(d.total_g/1000).toFixed(2)} kg)</span>
      </div>
    </div>
  )
}

function RegionDetail({ d }: { d: RegionComposition }) {
  const rows = [
    { lbl: 'Fat',  val: d.fat_g,  pct: d.fat_pct,  color: C.pink },
    { lbl: 'Lean', val: d.lean_g, pct: d.lean_pct, color: C.cyan },
    { lbl: 'Bone', val: d.bone_g, pct: d.bone_pct, color: C.bone },
  ]
  return (
    <div style={{ marginTop: 6 }}>
      {rows.map(r => (
        <div key={r.lbl} style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 5 }}>
          <div style={{ width: 28, fontSize: 8, color: r.color, fontWeight: 600 }}>{r.lbl}</div>
          <div style={{ flex: 1, height: 9, background: C.border, borderRadius: 2, overflow: 'hidden' }}>
            <div style={{ width: `${r.pct}%`, height: '100%', background: r.color }} />
          </div>
          <div style={{ width: 70, fontSize: 7.5, color: C.gray, textAlign: 'right' }}>
            {r.pct}% · {(r.val/1000).toFixed(2)} kg
          </div>
        </div>
      ))}
    </div>
  )
}

function WHO_TScoreViz({ t }: { t: number }) {
  // Scale: -4 to +4
  const markerPct = ((t + 4) / 8) * 100
  return (
    <div>
      <div style={{ position: 'relative', marginBottom: 6 }}>
        <div style={{ display: 'flex', height: 18, borderRadius: 4, overflow: 'hidden' }}>
          <div style={{ width: '18.75%', background: C.red,     display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <span style={{ fontSize: 7, color: '#fff', fontWeight: 700 }}>Osteoporosis</span>
          </div>
          <div style={{ width: '18.75%', background: C.amber,   display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <span style={{ fontSize: 7, color: '#fff', fontWeight: 700 }}>Osteopenia</span>
          </div>
          <div style={{ width: '62.5%',  background: C.green,   display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <span style={{ fontSize: 7, color: '#fff', fontWeight: 700 }}>Normal</span>
          </div>
        </div>
        {/* Marker */}
        <div style={{ position: 'absolute', left: `${Math.min(Math.max(markerPct, 1), 99)}%`,
          top: -4, width: 4, height: 26, background: C.white, borderRadius: 2,
          transform: 'translateX(-50%)', boxShadow: '0 0 4px rgba(0,0,0,0.5)' }} />
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 7, color: C.gray }}>
        <span>−4</span><span>−2.5</span><span>−1</span><span>0</span><span>+4</span>
      </div>
    </div>
  )
}

function ScoreBlock({ label, value, meaning }: { label: string; value: number; meaning: string }) {
  const color = value <= -2.5 ? C.red : value <= -1 ? C.amber : C.greenLt
  return (
    <div>
      <div className="lbl">{label}</div>
      <div style={{ fontSize: 26, fontWeight: 800, color, lineHeight: 1 }}>
        {value >= 0 ? '+' : ''}{value.toFixed(1)}
      </div>
      <div style={{ fontSize: 7, color: C.gray, marginTop: 2 }}>{meaning}</div>
    </div>
  )
}

function ScoreExplain({ title, color, children }: {
  title: string; color: string; children: React.ReactNode
}) {
  return (
    <div style={{ flex: 1, background: C.bg, borderRadius: 6, padding: '8px 10px' }}>
      <div style={{ fontSize: 9, fontWeight: 700, color, marginBottom: 5 }}>{title}</div>
      <div style={{ fontSize: 8, color: C.gray, lineHeight: 1.6 }}>{children}</div>
    </div>
  )
}

function BoneRegionBars({ regions }: { regions: ReportData['bone']['regions'] }) {
  const order = ['Head', 'Arms', 'Ribs', 'Spine', 'Pelvis', 'Legs', 'Trunk']
  const maxBmd = 2.5
  const rows = order.map(n => ({ name: n, d: regions[n] })).filter(r => r.d)
  return (
    <div style={{ marginTop: 6 }}>
      {rows.map(({ name, d }) => (
        <div key={name} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
          <div style={{ width: 40, fontSize: 8.5, color: C.grayLt }}>{name}</div>
          <div style={{ flex: 1, height: 12, background: C.border, borderRadius: 2, overflow: 'hidden' }}>
            <div style={{ width: `${Math.min(d!.bmd / maxBmd * 100, 100)}%`,
              height: '100%', background: C.teal }} />
          </div>
          <div style={{ width: 60, fontSize: 8, color: C.gray, textAlign: 'right', fontFamily: 'monospace' }}>
            {d!.bmd.toFixed(3)} g/cm²
          </div>
        </div>
      ))}
    </div>
  )
}

function AlmiBadge({ rating }: { rating: ReportData['computed']['almi_rating'] }) {
  const cfg = {
    low:    { lbl: 'Low Muscle Mass',   color: C.amber   },
    normal: { lbl: 'Normal Muscle',     color: C.greenLt },
    high:   { lbl: 'High Muscle Mass',  color: C.cyan    },
  }[rating]
  return (
    <span className="tag" style={{ color: cfg.color, background: cfg.color + '22',
      border: `1px solid ${cfg.color}44` }}>{cfg.lbl}</span>
  )
}

function BoneClassBadge({ cls }: { cls: ReportData['bone']['classification'] }) {
  const cfg = {
    normal:       { lbl: 'Normal Bone Density', color: C.greenLt },
    low_mass:     { lbl: 'Osteopenia',           color: C.amber   },
    osteoporosis: { lbl: 'Osteoporosis',         color: C.red     },
  }[cls]
  return (
    <span className="tag" style={{ color: cfg.color, background: cfg.color + '22',
      border: `1px solid ${cfg.color}44`, fontSize: 10, padding: '4px 10px' }}>{cfg.lbl}</span>
  )
}

// ── Clinical summary builder ───────────────────────────────────────────────────

function buildSummaryItems(
  comp: ReportData['composition'],
  calc: ReportData['computed'],
  bone: ReportData['bone'],
) {
  type Status = 'good' | 'warn' | 'alert' | 'info'
  const items: Array<{ title: string; body: string; status: Status }> = []

  // Body fat
  if (comp.fat_pct < 20) items.push({ status: 'good',
    title: 'Body Fat: Athletic',
    body: `${comp.fat_pct}% — excellent. Well within the athletic range for your age and sex.` })
  else if (comp.fat_pct < 25) items.push({ status: 'good',
    title: 'Body Fat: Fit',
    body: `${comp.fat_pct}% — healthy fit range. No intervention needed.` })
  else if (comp.fat_pct < 30) items.push({ status: 'warn',
    title: 'Body Fat: Borderline',
    body: `${comp.fat_pct}% — borderline acceptable. Target &lt;25% through diet and cardio.` })
  else items.push({ status: 'alert',
    title: 'Body Fat: Elevated',
    body: `${comp.fat_pct}% — above healthy range. Reducing body fat will improve metabolic health and reduce cardiometabolic risk.` })

  // A/G ratio — context-aware
  if (comp.ag_ratio < 0.8) {
    items.push({ status: 'good',
      title: 'Android/Gynoid: Healthy Distribution',
      body: `A/G ${comp.ag_ratio} — fat stored preferentially in lower body (gynoid pattern). Associated with lower metabolic risk.` })
  } else if (comp.ag_ratio < 1.0) {
    items.push({ status: 'warn',
      title: 'Android/Gynoid: Moderate',
      body: `A/G ${comp.ag_ratio} — mild central tendency. Reducing android (abdominal) fat is beneficial.` })
  } else if (calc.almi_rating === 'high') {
    // Elevated A/G but high muscle mass — downgrade to info, explain context
    items.push({ status: 'info',
      title: 'Android/Gynoid: Context — Muscular',
      body: `A/G ${comp.ag_ratio} — slightly central, but with an ALMI of ${calc.almi} kg/m² (high muscle mass), the gynoid region is muscle-dominant (${comp.regions.Gynoid?.lean_pct ?? '—'}% lean). Monitor android fat% (${comp.android_fat_pct}%) rather than the ratio alone.` })
  } else {
    items.push({ status: 'alert',
      title: 'Android/Gynoid: Elevated',
      body: `A/G ${comp.ag_ratio} — central/abdominal fat pattern. Higher cardiometabolic risk. Prioritise reducing android fat through diet and aerobic exercise.` })
  }

  // ALM / muscle
  if (calc.almi_rating === 'high') items.push({ status: 'good',
    title: 'Muscle Mass: Excellent',
    body: `ALMI ${calc.almi} kg/m² — above-average appendicular lean mass for your age. Strong musculoskeletal profile; well above sarcopenia threshold (7.26 kg/m²).` })
  else if (calc.almi_rating === 'normal') items.push({ status: 'good',
    title: 'Muscle Mass: Normal',
    body: `ALMI ${calc.almi} kg/m² — within normal range. Maintain with regular resistance training (2–3×/week).` })
  else items.push({ status: 'warn',
    title: 'Muscle Mass: Low',
    body: `ALMI ${calc.almi} kg/m² — below reference range (sarcopenia threshold 7.26 kg/m²). Resistance training and adequate protein intake (1.6 g/kg) recommended.` })

  // FMI
  if (calc.fat_risk === 'low') items.push({ status: 'good',
    title: 'Fat Mass Index: Normal',
    body: `FMI ${calc.fmi} kg/m² — normal range. FMI is more precise than BMI as it isolates fat mass from muscle mass.` })
  else if (calc.fat_risk === 'moderate') items.push({ status: 'warn',
    title: 'Fat Mass Index: Borderline',
    body: `FMI ${calc.fmi} kg/m² — mildly elevated. Target &lt;6 kg/m² (men) / &lt;9 kg/m² (women) through sustained caloric deficit and cardio.` })
  else items.push({ status: 'alert',
    title: 'Fat Mass Index: Elevated',
    body: `FMI ${calc.fmi} kg/m² — significantly elevated. Unlike BMI, FMI directly measures excess fat mass and is not affected by high muscle mass.` })

  // Bone
  if (bone.classification === 'normal') items.push({ status: 'good',
    title: 'Bone Density: Normal',
    body: `Total BMD ${bone.total_bmd.toFixed(3)} g/cm², T-score ${bone.total_t >= 0 ? '+' : ''}${bone.total_t.toFixed(1)} — excellent bone health. No bone density concerns at this time.` })
  else if (bone.classification === 'low_mass') items.push({ status: 'warn',
    title: 'Bone Density: Osteopenia',
    body: `T-score ${bone.total_t.toFixed(1)} — below normal. Review calcium (1000–1200 mg/day), vitamin D (800–2000 IU/day), and ensure weight-bearing exercise.` })
  else items.push({ status: 'alert',
    title: 'Bone Density: Osteoporosis Range',
    body: `T-score ${bone.total_t.toFixed(1)} — clinical evaluation and FRAX fracture risk assessment recommended.` })

  return items
}

// ── Helper functions ──────────────────────────────────────────────────────────

function statusStyle(s: string) {
  return ({
    good:  { bg: '#0a2a0a', border: C.greenLt },
    warn:  { bg: '#2a1a00', border: C.amber   },
    alert: { bg: '#2a0a0a', border: C.red     },
    info:  { bg: '#0a1a2a', border: C.tealLt  },
  } as Record<string, { bg: string; border: string }>)[s] ?? { bg: C.card, border: C.border }
}

function boneCardBg(cls: string) {
  return cls === 'osteoporosis' ? '#2a0a0a' : cls === 'low_mass' ? '#2a1a00' : '#0a1f0a'
}
function boneColor(cls: string) {
  return cls === 'osteoporosis' ? C.red : cls === 'low_mass' ? C.amber : C.greenLt
}
function fmiColor(fmi: number, male: boolean) {
  const hi = male ? 6 : 9; const vhi = male ? 9 : 13
  return fmi < hi ? C.greenLt : fmi < vhi ? C.amber : C.red
}
function bmiNote(bmi: number) {
  if (bmi < 18.5) return 'Underweight'
  if (bmi < 25)   return 'Normal weight'
  if (bmi < 30)   return 'Overweight'
  return 'Obese class I+'
}
function almiNote(r: string) {
  return r === 'high' ? '● Excellent — above reference' : r === 'low' ? '▲ Below reference' : '● Within normal range'
}
function fmiNote(r: string, gender: string) {
  const m = gender.toLowerCase().startsWith('m')
  return r === 'low' ? `● Normal (men <6, women <9 kg/m²)` : r === 'moderate' ? '▲ Borderline elevated' : '▲ Elevated'
}
