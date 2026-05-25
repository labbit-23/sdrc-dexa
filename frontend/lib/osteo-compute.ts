import type {
  RawOsteoData, OsteoReportData, OsteoClassification,
  SpineRegions, FemurRegions, OsteoRegion,
} from './osteo-types'

function classify(t: number | null | undefined): OsteoClassification {
  if (t == null) return 'normal'
  if (t <= -2.5) return 'osteoporosis'
  if (t <= -1.0) return 'osteopenia'
  return 'normal'
}

function lowestT(...vals: (number | null | undefined)[]): number | null {
  const valid = vals.filter((v): v is number => v != null)
  return valid.length ? Math.min(...valid) : null
}

// T or Z > +4 on any diagnostic sub-region indicates prosthesis artifact
function isImplantSide(femur: FemurRegions): boolean {
  for (const key of ['Neck', 'Total'] as const) {
    const r = femur[key]
    if (!r) continue
    if ((r.T != null && r.T > 4) || (r.Z != null && r.Z > 4)) return true
  }
  return false
}

function parseRegion(raw: Record<string, unknown>): OsteoRegion | undefined {
  const bmd = parseFloat(raw.bmd as string)
  if (isNaN(bmd) || bmd === 0) return undefined
  return {
    bmd,
    bmc:  raw.bmc  != null ? parseFloat(raw.bmc  as string) || undefined : undefined,
    area: raw.area != null ? parseFloat(raw.area as string) || undefined : undefined,
    T:    raw.T    != null ? parseFloat(raw.T    as string) ?? undefined : undefined,
    Z:    raw.Z    != null ? parseFloat(raw.Z    as string) ?? undefined : undefined,
    pYA:  raw.pYA  != null ? parseFloat(raw.pYA  as string) || undefined : undefined,
  }
}

function parseSpine(raw: Record<string, Record<string, unknown>>): SpineRegions {
  const out: SpineRegions = {}
  for (const [key, val] of Object.entries(raw)) {
    const r = parseRegion(val)
    if (!r) continue
    if (key === 'L1') out.L1 = r
    else if (key === 'L2') out.L2 = r
    else if (key === 'L3') out.L3 = r
    else if (key === 'L4') out.L4 = r
    else if (key === 'L1-L4') out['L1-L4'] = r
  }
  return out
}

function parseFemur(raw: Record<string, Record<string, unknown>>): FemurRegions {
  const out: FemurRegions = {}
  for (const [key, val] of Object.entries(raw)) {
    const r = parseRegion(val)
    if (!r) continue
    if (key === 'Neck')       out.Neck       = r
    else if (key === 'Trochanter') out.Trochanter = r
    else if (key === 'Wards') out.Wards      = r
    else if (key === 'Total') out.Total      = r
  }
  return out
}

export function computeOsteoData(
  raw: RawOsteoData,
  patientId: string,
  imageBaseUrl: string,
): OsteoReportData {
  const { patient: pat, session } = raw

  const scanDt = new Date(session.scan_date)
  const scanDate = scanDt.toISOString().slice(0, 10)
  const scanTime = session.scan_date.slice(11, 19)

  const dob    = pat.dob ? new Date(pat.dob) : null
  const ageYrs = dob ? parseFloat(((scanDt.getTime() - dob.getTime()) / 31557600000).toFixed(1)) : 0
  const gender = pat.gender || 'Female'
  const premenopausal = gender.toLowerCase().startsWith('f') && ageYrs < 50

  const spine      = parseSpine((session.spine      || {}) as Record<string, Record<string, unknown>>)
  const left_femur = parseFemur((session.left_femur  || {}) as Record<string, Record<string, unknown>>)
  const right_femur = parseFemur((session.right_femur || {}) as Record<string, Record<string, unknown>>)

  const spineTotal = spine['L1-L4']
  const spine_t    = spineTotal?.T ?? null
  const spine_z    = spineTotal?.Z ?? null

  const left_neck_t  = left_femur.Neck?.T  ?? null
  const right_neck_t = right_femur.Neck?.T ?? null

  const left_implant  = isImplantSide(left_femur)
  const right_implant = isImplantSide(right_femur)

  // ISCD: lowest of Femoral Neck and Total Hip; exclude prosthesis sides
  const leftHipT  = left_implant  ? null : lowestT(left_femur.Total?.T, left_neck_t)
  const rightHipT = right_implant ? null : lowestT(right_femur.Total?.T, right_neck_t)
  const lowest_hip_t = lowestT(leftHipT, rightHipT)

  // Bilateral = both sides present and round to the same 1-dp value
  const hip_bilateral =
    leftHipT != null && rightHipT != null &&
    leftHipT.toFixed(1) === rightHipT.toFixed(1)

  const lowest_hip_side: 'left' | 'right' | null =
    leftHipT == null && rightHipT == null ? null
    : leftHipT == null ? 'right'
    : rightHipT == null ? 'left'
    : leftHipT <= rightHipT ? 'left' : 'right'

  const lowestFemur = lowest_hip_side === 'right' ? right_femur : lowest_hip_side === 'left' ? left_femur : null
  const lowest_hip_z = lowestFemur?.Total?.Z ?? lowestFemur?.Neck?.Z ?? null

  let lowest_hip_site: 'neck' | 'total' | null = null
  if (lowestFemur && !left_implant && !right_implant) {
    const neckT  = lowestFemur.Neck?.T  ?? null
    const totalT = lowestFemur.Total?.T ?? null
    if (neckT != null && totalT != null) lowest_hip_site = neckT <= totalT ? 'neck' : 'total'
    else if (neckT  != null) lowest_hip_site = 'neck'
    else if (totalT != null) lowest_hip_site = 'total'
  }

  const overall_t = lowestT(spine_t, leftHipT, rightHipT)
  const overall_class = classify(overall_t)

  const bmi = pat.height_cm > 0
    ? parseFloat((pat.weight_kg / (pat.height_cm / 100) ** 2).toFixed(1))
    : (pat.bmi ?? 0)

  return {
    patient: {
      id:         patientId,
      name:       `${pat.name} ${pat.title}`.trim(),
      first_name: pat.name,
      last_name:  pat.title,
      gender,
      age:        ageYrs,
      dob_str:    pat.dob || '',
      height_cm:  pat.height_cm,
      weight_kg:  pat.weight_kg,
      bmi,
      physician:  pat.physician || '',
      scan_date:  scanDate,
      scan_time:  scanTime,
      scanner:    session.scanner_serial || '',
      software:   session.software || '',
    },
    spine,
    left_femur,
    right_femur,
    summary: {
      spine_t,
      spine_z,
      spine_class: classify(spine_t),
      left_neck_t,
      right_neck_t,
      lowest_hip_t,
      lowest_hip_z,
      lowest_hip_side,
      lowest_hip_site,
      hip_bilateral,
      overall_class,
      premenopausal,
      left_implant,
      right_implant,
    },
    images: {
      spine_url:       `${imageBaseUrl}/img_spine.png`,
      left_femur_url:  `${imageBaseUrl}/img_left_femur.png`,
      right_femur_url: `${imageBaseUrl}/img_right_femur.png`,
    },
  }
}
