// Raw MDB snapshot shape (from collect.py → mdb_snapshot())
export interface MdbCompositionRow {
  label: string
  fat_mass: string
  lean_mass: string
  bone_mass: string
  img_handle?: string
  comp_handle?: string
  method?: string
}

export interface MdbSnapshot {
  patient_id: string
  snapshot_ts: string
  patients: Record<string, {
    first_name: string
    last_name: string
    patient_id: string
    birth_time: string
    height: string
    weight: string
    gender: string
    ethnicity: string
    physician: string
  }>
  exams: Array<{
    img_handle: string
    scan_handle: string
    pat_handle: string
    scantype: string
    _acq_dt: string
    scanner_id: string
    acquisition_version: string
    height: string
    weight: string
  }>
  composition: Record<string, MdbCompositionRow[]>
  densitometry: Record<string, Array<{
    label: string
    bmd: string
    bmc: string
    area: string
    dens_handle: string
  }>>
}

// Parsed XPS bone data (from parse_totalbody_bone)
export interface XpsBoneData {
  patient: XpsPatient
  regions: Record<string, { bmd: number; T?: number; Z?: number }>
}

// Parsed XPS composition data (from parse_totalbody_composition)
export interface XpsCompositionData {
  patient: XpsPatient
  fat_g?: number
  lean_g?: number
  bmc_g?: number
  fat_free_g?: number
  total_kg?: number
  fat_pct?: number
  android_fat_pct?: number
  gynoid_fat_pct?: number
  ag_ratio?: number
  centile?: number
  bmi?: number
}

export interface XpsPatient {
  name: string
  title: string
  dob_str: string
  age_str: string
  height_cm: number
  weight_kg: number
  gender: string
  scan_date_str: string
  scan_time_str: string
  physician: string
}

// Combined raw data file
export interface RawPatientData {
  mdb_snapshot: MdbSnapshot
  xps_bone: XpsBoneData
  xps_composition: XpsCompositionData
}

// ── Computed / normalised report data ─────────────────────────────────────────

export interface RegionComposition {
  fat_g: number
  lean_g: number
  bone_g: number
  total_g: number
  fat_pct: number
  lean_pct: number
  bone_pct: number
}

export type RegionName = 'Arms' | 'Trunk' | 'Legs' | 'Total' | 'Android' | 'Gynoid'

export interface ReportData {
  patient: {
    id: string
    name: string           // "SRINIVAS G MR"
    first_name: string
    last_name: string
    gender: string
    age: number
    dob_str: string
    height_cm: number
    weight_entered_kg: number   // what was typed in at registration
    weight_measured_kg: number  // actual scan-measured (fat+lean+bone)
    bmi_entered: number
    bmi_measured: number
    ethnicity: string
    physician: string
    scan_date: string
    scan_time: string
    scanner: string
    software: string
  }
  composition: {
    regions: Partial<Record<RegionName, RegionComposition>>
    // Total body summary
    fat_pct: number
    fat_g: number
    lean_g: number
    bmc_g: number
    total_g: number
    // Android / Gynoid
    android_fat_pct: number
    gynoid_fat_pct: number
    ag_ratio: number           // fat% ratio
    centile?: number
  }
  computed: {
    alm_kg: number             // Arms lean + Legs lean (0 = unavailable)
    alm_available: boolean     // false when MDB regional composition is missing
    almi: number               // ALM / height²
    fmi: number                // fat_kg / height²
    lmi: number                // lean_kg / height²
    rmr_kcal: number           // Katch-McArdle
    fat_risk: 'low' | 'moderate' | 'high'   // FMI-based
    almi_rating: 'low' | 'normal' | 'high'
  }
  bone: {
    total_bmd: number
    total_t: number
    total_z: number
    regions: Partial<Record<string, { bmd: number; T?: number; Z?: number }>>
    classification: 'normal' | 'low_mass' | 'osteoporosis'
  }
  images: {
    fat_lean_url: string
    fat_gradient_url: string
    bone_url: string
    composite_url: string
  }
}
