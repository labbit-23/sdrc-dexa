import type {
  RawPatientData, RegionComposition, RegionName, ReportData,
} from './bmd-types'

const COMP_LABELS: Record<number, RegionName> = {
  1: 'Arms', 2: 'Legs', 3: 'Trunk', 7: 'Total', 59: 'Android', 60: 'Gynoid',
}

function parseRegions(snapshot: RawPatientData['mdb_snapshot']) {
  const compEntries = Object.values(snapshot.composition)
  if (!compEntries.length) return {} as Partial<Record<RegionName, RegionComposition>>

  // Use the first (and usually only) img_handle's rows
  const rows = compEntries[0]
  const out: Partial<Record<RegionName, RegionComposition>> = {}

  for (const row of rows) {
    const label = parseInt(row.label)
    const name = COMP_LABELS[label]
    if (!name) continue
    const fat  = Math.abs(parseFloat(row.fat_mass)  || 0)
    const lean = Math.abs(parseFloat(row.lean_mass) || 0)
    const bone = Math.abs(parseFloat(row.bone_mass) || 0)
    const total = fat + lean + bone
    out[name] = {
      fat_g:    Math.round(fat),
      lean_g:   Math.round(lean),
      bone_g:   Math.round(bone),
      total_g:  Math.round(total),
      fat_pct:  total > 0 ? parseFloat((fat  / total * 100).toFixed(1)) : 0,
      lean_pct: total > 0 ? parseFloat((lean / total * 100).toFixed(1)) : 0,
      bone_pct: total > 0 ? parseFloat((bone / total * 100).toFixed(1)) : 0,
    }
  }
  return out
}

function boneClassify(t: number): ReportData['bone']['classification'] {
  if (t <= -2.5) return 'osteoporosis'
  if (t <= -1.0) return 'low_mass'
  return 'normal'
}

// FMI reference ranges for men (kg/m²): normal 3–6, elevated 6–9, obese >9
// For women: normal 5–9, elevated 9–13
function fatRisk(fmi: number, gender: string): ReportData['computed']['fat_risk'] {
  const male = gender.toLowerCase().startsWith('m')
  if (male) return fmi < 6 ? 'low' : fmi < 9 ? 'moderate' : 'high'
  return fmi < 9 ? 'low' : fmi < 13 ? 'moderate' : 'high'
}

// ALMI reference (appendicular lean mass index) for men: low < 7.26, normal 7.26–9.2, high > 9.2
function almiRating(almi: number, gender: string): ReportData['computed']['almi_rating'] {
  const male = gender.toLowerCase().startsWith('m')
  const lo = male ? 7.26 : 5.67
  const hi = male ? 9.20 : 7.5
  if (almi < lo) return 'low'
  if (almi > hi) return 'high'
  return 'normal'
}

export function computeReportData(
  raw: RawPatientData,
  patientId: string,
  imageBaseUrl: string,
): ReportData {
  const snap  = raw.mdb_snapshot
  const xpsBone = raw.xps_bone
  const xpsComp = raw.xps_composition

  // ── Patient demographics ──────────────────────────────────────────────────
  const patRow = Object.values(snap.patients)[0]
  const examRow = snap.exams[0]

  const xpsPat  = xpsBone?.patient ?? xpsComp?.patient
  const heightCm = xpsPat?.height_cm ?? parseFloat(patRow?.height ?? '0')
  const weightEnteredKg = xpsPat?.weight_kg ?? parseFloat(patRow?.weight ?? '0')
  const gender   = xpsPat?.gender ?? patRow?.gender ?? 'Male'
  const heightM  = heightCm / 100
  const bmiEntered = heightM > 0 ? parseFloat((weightEnteredKg / heightM ** 2).toFixed(1)) : 0

  // Age from XPS string (most reliable)
  const age = xpsPat?.age_str ? parseFloat(xpsPat.age_str) : 0

  // Scan date / time
  const scanDate = xpsPat?.scan_date_str ?? examRow?._acq_dt?.slice(0, 10) ?? ''
  const scanTime = xpsPat?.scan_time_str ?? ''

  // ── Composition regions from MDB ──────────────────────────────────────────
  const regions = parseRegions(snap)

  // Fall back to XPS totals if MDB composition is empty
  const totalRegion = regions.Total
  const fat_g  = totalRegion?.fat_g  ?? xpsComp?.fat_g  ?? 0
  const lean_g = totalRegion?.lean_g ?? xpsComp?.lean_g ?? 0
  const bmc_g  = totalRegion?.bone_g ?? xpsComp?.bmc_g  ?? 0
  const total_g = fat_g + lean_g + bmc_g
  const fat_pct = total_g > 0
    ? parseFloat((fat_g / total_g * 100).toFixed(1))
    : (xpsComp?.fat_pct ?? 0)

  const weightMeasuredKg = total_g / 1000
  const bmiMeasured = heightM > 0
    ? parseFloat((weightMeasuredKg / heightM ** 2).toFixed(1))
    : bmiEntered

  // Android / Gynoid — prefer MDB fat%, fall back to XPS
  const androidFatPct = regions.Android?.fat_pct ?? xpsComp?.android_fat_pct ?? 0
  const gynoidFatPct  = regions.Gynoid?.fat_pct  ?? xpsComp?.gynoid_fat_pct  ?? 0
  const agRatio = gynoidFatPct > 0
    ? parseFloat((androidFatPct / gynoidFatPct).toFixed(2))
    : (xpsComp?.ag_ratio ?? 0)

  // ── Computed metrics ──────────────────────────────────────────────────────
  const armsLean    = regions.Arms?.lean_g ?? 0
  const legsLean    = regions.Legs?.lean_g ?? 0
  const alm_available = armsLean > 0 || legsLean > 0
  const alm_kg      = (armsLean + legsLean) / 1000
  const almi        = alm_available && heightM > 0 ? parseFloat((alm_kg / heightM ** 2).toFixed(2)) : 0
  const fmi      = heightM > 0 ? parseFloat((fat_g / 1000 / heightM ** 2).toFixed(2)) : 0
  const lmi      = heightM > 0 ? parseFloat((lean_g / 1000 / heightM ** 2).toFixed(2)) : 0
  const rmr_kcal = Math.round(370 + 21.6 * (lean_g / 1000))  // Katch-McArdle

  // ── Bone ─────────────────────────────────────────────────────────────────
  const boneRegions = xpsBone?.regions ?? {}
  const totalBone = boneRegions['Total'] ?? {}
  const totalBmd  = totalBone.bmd ?? 0
  const totalT    = totalBone.T  ?? 0
  const totalZ    = totalBone.Z  ?? 0

  return {
    patient: {
      id:                  patientId,
      name:                `${xpsPat?.name ?? patRow?.first_name} ${xpsPat?.title ?? patRow?.last_name}`.trim(),
      first_name:          xpsPat?.name ?? patRow?.first_name ?? '',
      last_name:           xpsPat?.title ?? patRow?.last_name ?? '',
      gender,
      age,
      dob_str:             xpsPat?.dob_str ?? '',
      height_cm:           heightCm,
      weight_entered_kg:   weightEnteredKg,
      weight_measured_kg:  parseFloat(weightMeasuredKg.toFixed(1)),
      bmi_entered:         bmiEntered,
      bmi_measured:        bmiMeasured,
      ethnicity:           patRow?.ethnicity ?? '',
      physician:           xpsPat?.physician ?? patRow?.physician ?? '',
      scan_date:           scanDate,
      scan_time:           scanTime,
      scanner:             examRow?.scanner_id ?? '',
      software:            examRow?.acquisition_version ?? '',
    },
    composition: {
      regions,
      fat_pct,
      fat_g,
      lean_g,
      bmc_g,
      total_g,
      android_fat_pct: androidFatPct,
      gynoid_fat_pct:  gynoidFatPct,
      ag_ratio:        agRatio,
      centile:         xpsComp?.centile,
    },
    computed: {
      alm_kg:        parseFloat(alm_kg.toFixed(1)),
      alm_available,
      almi,
      fmi,
      lmi,
      rmr_kcal,
      fat_risk:    fatRisk(fmi, gender),
      almi_rating: almiRating(almi, gender),
    },
    bone: {
      total_bmd:      totalBmd,
      total_t:        totalT,
      total_z:        totalZ,
      regions:        boneRegions,
      classification: boneClassify(totalT),
    },
    images: {
      fat_lean_url:     `${imageBaseUrl}/img_fat_lean.png`,
      fat_gradient_url: `${imageBaseUrl}/img_fat_gradient.png`,
      bone_url:         `${imageBaseUrl}/img_bone.png`,
      composite_url:    `${imageBaseUrl}/img_composite.png`,
    },
  }
}
