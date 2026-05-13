export type OsteoRegion = {
  bmd:   number
  bmc?:  number
  area?: number
  T?:    number
  Z?:    number
  pYA?:  number
}

export type SpineRegions = {
  L1?:    OsteoRegion
  L2?:    OsteoRegion
  L3?:    OsteoRegion
  L4?:    OsteoRegion
  'L1-L4'?: OsteoRegion
}

export type FemurRegions = {
  Neck?:       OsteoRegion
  Trochanter?: OsteoRegion
  Wards?:      OsteoRegion
  Total?:      OsteoRegion
}

export type OsteoClassification = 'normal' | 'osteopenia' | 'osteoporosis'

export type OsteoReportData = {
  patient: {
    id:          string
    name:        string
    first_name:  string
    last_name:   string
    gender:      string
    age:         number
    dob_str:     string
    height_cm:   number
    weight_kg:   number
    bmi:         number
    physician:   string
    scan_date:   string
    scan_time:   string
    scanner:     string
    software:    string
  }
  spine:        SpineRegions
  left_femur:   FemurRegions
  right_femur:  FemurRegions
  summary: {
    spine_t:         number | null   // L1-L4 total T
    spine_z:         number | null
    spine_class:     OsteoClassification
    left_neck_t:     number | null
    right_neck_t:    number | null
    lowest_hip_t:    number | null   // min of both neck T-scores
    lowest_hip_side: 'left' | 'right' | null
    hip_bilateral:   boolean              // both sides round to same 1-dp value
    overall_class:   OsteoClassification  // WHO: lowest T across all sites
    premenopausal:   boolean              // female < 50 → Z-score language
  }
  images: {
    spine_url?:        string
    left_femur_url?:   string
    right_femur_url?:  string
  }
}

// ── Raw data shape from Python pipeline ──────────────────────────────────
export type RawOsteoData = {
  patient: {
    pat_handle:  string
    patient_id:  string
    name:        string
    title:       string
    dob:         string   // "YYYY-MM-DD"
    gender:      string
    ethnicity:   string
    height_cm:   number
    weight_kg:   number
    bmi:         number
    physician:   string
  }
  session: {
    scan_date:      string   // "YYYY-MM-DD HH:MM:SS"
    scanner_serial: string
    software:       string
    ntx_filename?:  string
    spine:        Record<string, { bmd: number; bmc?: number; area?: number; T?: number; Z?: number; pYA?: number }>
    left_femur:   Record<string, { bmd: number; bmc?: number; area?: number; T?: number; Z?: number; pYA?: number }>
    right_femur:  Record<string, { bmd: number; bmc?: number; area?: number; T?: number; Z?: number; pYA?: number }>
  }
}
