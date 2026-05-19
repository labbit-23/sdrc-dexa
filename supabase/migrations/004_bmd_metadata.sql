-- ─────────────────────────────────────────────────────────────────────────────
-- 004_bmd_metadata.sql
--
-- Reference / decoder table for the GE Lunar DPX-NT MDB → PDF pipeline.
-- Pure documentation — not queried by app code (yet).
-- Records all institutional knowledge reverse-engineered from the SDRC scanner.
--
-- confidence values:
--   'confirmed'  — verified mathematically or cross-checked against XPS/machine
--   'inferred'   — consistent with observed data but not formally verified
--   'unknown'    — seen in data, meaning unclear
-- ─────────────────────────────────────────────────────────────────────────────

create table bmd_metadata (
  id          bigserial    primary key,
  category    text         not null,
  key         text         not null,
  label       text,                    -- human-readable name / mapped value
  unit        text,                    -- 'g' | 'pct×10' | null
  side        text,                    -- 'left' | 'right' | null (bilateral rows)
  confidence  text         not null default 'confirmed',
  notes       text,
  created_at  timestamptz  not null default now(),
  unique (category, key)
);

comment on table bmd_metadata is
  'Decoder / reference for GE Lunar DPX-NT MDB label and scantype integers. '
  'All mappings verified against SDRC scanner data unless noted otherwise.';

-- ─── MDB scan session structure ───────────────────────────────────────────────
-- The MDB Exams table has a scantype integer per image acquisition.
-- Sessions group multiple scantypes under one scan_handle.

insert into bmd_metadata (category, key, label, confidence, notes) values
  ('mdb_scantype', '0',  'Total Body',          'confirmed',
   'site=0 side=0. Standard whole-body DXA. Contains spine bone density (labels 19–22) '
   'and full composition (labels 1–3, 7, 51–60, 59–60). '
   'Also used as the spine img in osteo sessions when no scantype=10 is present.'),

  ('mdb_scantype', '1',  'Right Hip / Femur',   'confirmed',
   'site=1 side=2. Femur densitometry labels 0–4 (Neck/Wards/Trochanter/InterTroch/Total). '
   'NOTE: original GE spec incorrectly described this as spine — verified to be right femur.'),

  ('mdb_scantype', '2',  'Left Hip / Femur',    'confirmed',
   'site=1 side=1. Same label structure as scantype=1 but left side.'),

  ('mdb_scantype', '10', 'Lateral Spine / Total Body (alt firmware)', 'confirmed',
   'Lateral spine on standard firmware. On some DPX-NT firmware versions this is the '
   'total-body scantype instead. Parser treats scantype IN (0,10) as total-body candidates '
   'and picks the one whose img_handle starts with img_. '
   'mdb_scan_type is set to total_body if any exam in the session has scantype=10.'),

  ('mdb_scantype', '21', 'Report Record — skip', 'confirmed',
   'Internal GE report/print record. No clinical data. Always skipped by parser.');


-- ─── Femur densitometry labels ────────────────────────────────────────────────
-- Same label set for both left (scantype=2) and right (scantype=1) femur.

insert into bmd_metadata (category, key, label, confidence, notes) values
  ('femur_label', '0', 'Neck',       'confirmed', 'Femoral neck — primary ISCD site for osteoporosis diagnosis'),
  ('femur_label', '1', 'Wards',      'confirmed', 'Ward''s triangle — high trabecular content, sensitive but variable'),
  ('femur_label', '2', 'Trochanter', 'confirmed', 'Greater trochanter region'),
  ('femur_label', '3', 'InterTroch', 'confirmed', 'Intertrochanteric region'),
  ('femur_label', '4', 'Total',      'confirmed', 'Total hip — preferred ISCD site when available');


-- ─── Spine densitometry labels (within total-body img, scantype=0) ────────────
-- These live in the Densitometry table linked to the total-body img_handle.

insert into bmd_metadata (category, key, label, confidence, notes) values
  ('spine_label', '19', 'L1',    'confirmed', 'First lumbar vertebra'),
  ('spine_label', '20', 'L2',    'confirmed', 'Second lumbar vertebra'),
  ('spine_label', '21', 'L3',    'confirmed', 'Third lumbar vertebra'),
  ('spine_label', '22', 'L4',    'confirmed', 'Fourth lumbar vertebra'),
  ('spine_label', '26', 'L1-L2', 'confirmed', 'Combined L1–L2 region'),
  ('spine_label', '27', 'L1-L3', 'confirmed', 'Combined L1–L3 region'),
  ('spine_label', '28', 'L1-L4', 'confirmed', 'Combined L1–L4 — primary reporting region for spine BMD'),
  ('spine_label', '29', 'L2-L3', 'confirmed', 'Combined L2–L3 region'),
  ('spine_label', '30', 'L2-L4', 'confirmed', 'Combined L2–L4 region'),
  ('spine_label', '31', 'L3-L4', 'confirmed', 'Combined L3–L4 region');


-- ─── Total-body composition labels (Composition table) ───────────────────────
-- Values stored in GRAMS (e.g. fat_mass=15000 → 15 kg fat).
-- Verified against SDRC scanner display and XPS cross-check.

insert into bmd_metadata (category, key, label, unit, confidence, notes) values
  ('comp_label_totalbody', '1',  'Arms',    'g', 'confirmed',
   'Aggregate both arms. Sum of left_arm (label 51) + right_arm (label 55).'),
  ('comp_label_totalbody', '2',  'Legs',    'g', 'confirmed',
   'Aggregate both legs. Sum of left_leg (label 52) + right_leg (label 56).'),
  ('comp_label_totalbody', '3',  'Trunk',   'g', 'confirmed',
   'Aggregate trunk. Sum of left_trunk (label 53) + right_trunk (label 57).'),
  ('comp_label_totalbody', '7',  'Total',   'g', 'confirmed',
   'Whole-body total. Used to distinguish true total-body rows from osteo estimated rows: '
   'bone_mass > 0 on label=7 means this is a real total-body scan entry.'),
  ('comp_label_totalbody', '59', 'Android', 'g', 'confirmed',
   'Abdominal region. Used as numerator of Android/Gynoid (A/G) ratio.'),
  ('comp_label_totalbody', '60', 'Gynoid',  'g', 'confirmed',
   'Hip and thigh region. Used as denominator of A/G ratio.');


-- ─── Bilateral (left/right) composition labels ────────────────────────────────
-- Present in total-body scans only. Values in GRAMS.
-- Verified: label_51_fat + label_55_fat = label_1_fat (Arms total) — math checks out.
-- All SDRC total-body scans confirmed to have these 8 rows (18 rows total with aggregates).

insert into bmd_metadata (category, key, label, unit, side, confidence, notes) values
  ('comp_label_bilateral', '51', 'Left Arm',    'g', 'left',  'confirmed',
   'Verified: label_51 + label_55 = label_1 (Arms aggregate). Cross-checked with machine display.'),
  ('comp_label_bilateral', '52', 'Left Leg',    'g', 'left',  'confirmed',
   'Verified: label_52 + label_56 = label_2 (Legs aggregate).'),
  ('comp_label_bilateral', '53', 'Left Trunk',  'g', 'left',  'confirmed',
   'Verified: label_53 + label_57 = label_3 (Trunk aggregate).'),
  ('comp_label_bilateral', '54', 'Left Total',  'g', 'left',  'confirmed',
   'Verified: label_54 + label_58 = label_7 (Total).'),
  ('comp_label_bilateral', '55', 'Right Arm',   'g', 'right', 'confirmed', null),
  ('comp_label_bilateral', '56', 'Right Leg',   'g', 'right', 'confirmed', null),
  ('comp_label_bilateral', '57', 'Right Trunk', 'g', 'right', 'confirmed', null),
  ('comp_label_bilateral', '58', 'Right Total', 'g', 'right', 'confirmed', null);


-- ─── Osteo estimated composition labels ───────────────────────────────────────
-- GE Lunar derives a rough body composition estimate from the AP Spine + Femur scan.
-- IMPORTANT: values are stored as percentage×10 — NOT grams.
--   e.g. fat_mass=398.5 → 39.85% body fat
-- Confirmed against GE Lunar DPX display for patient 20260513066.
-- Only Total / Android / Gynoid fat_pct are used in reporting (no true mass available).

insert into bmd_metadata (category, key, label, unit, confidence, notes) values
  ('comp_label_osteo_estimated', '0', 'Total',          'pct×10', 'confirmed',
   'Estimated whole-body composition from spine+femur scan. fat_mass÷10 = fat%. Not comparable to true total-body grams.'),
  ('comp_label_osteo_estimated', '1', 'AP Spine Region','pct×10', 'confirmed',
   'Estimated composition of the AP spine analysis region. label=1 overlaps with Arms in total-body label set '
   'but is ignored in osteo reporting — only Total/Android/Gynoid are surfaced.'),
  ('comp_label_osteo_estimated', '5', 'Android',        'pct×10', 'confirmed',
   'Estimated android region fat%. Note: different label (5) from total-body android (59).'),
  ('comp_label_osteo_estimated', '6', 'Gynoid',         'pct×10', 'confirmed',
   'Estimated gynoid region fat%. Note: different label (6) from total-body gynoid (60).');


-- ─── Total-body BONE density region labels (Densitometry table, scantype=10) ──
-- Separate from composition. Verified against XPS output and Densitometry rows.

insert into bmd_metadata (category, key, label, confidence, notes) values
  ('bone_label_totalbody', '0', 'Head',   'confirmed', null),
  ('bone_label_totalbody', '1', 'Arms',   'confirmed', null),
  ('bone_label_totalbody', '2', 'Legs',   'confirmed', null),
  ('bone_label_totalbody', '3', 'Trunk',  'confirmed', null),
  ('bone_label_totalbody', '4', 'Ribs',   'confirmed', null),
  ('bone_label_totalbody', '5', 'Pelvis', 'confirmed', null),
  ('bone_label_totalbody', '6', 'Spine',  'confirmed', null),
  ('bone_label_totalbody', '7', 'Total',  'confirmed', 'Whole-body BMD. Used for T-score / Z-score / bone classification.');


-- ─── Unknown / excluded labels ────────────────────────────────────────────────
-- Appear in the Composition table for some scans. Always have negative values
-- for fat_mass / lean_mass / bone_mass — physically impossible for tissue mass.
-- Excluded from all calculations. GE internal use suspected but unconfirmed.

insert into bmd_metadata (category, key, label, confidence, notes) values
  ('comp_label_unknown', '100', 'Unknown', 'unknown',
   'Negative values observed in all scans. Excluded from all calculations. '
   'GE internal use suspected — no documentation available.'),
  ('comp_label_unknown', '110', 'Unknown', 'unknown',
   'Negative values observed in all scans. Excluded from all calculations. '
   'GE internal use suspected — no documentation available.'),
  ('comp_label_unknown', '120', 'Unknown', 'unknown',
   'Negative values observed in all scans. Excluded from all calculations. '
   'GE internal use suspected — no documentation available.'),
  ('comp_label_unknown', '130', 'Unknown', 'unknown',
   'Negative values observed in all scans. Excluded from all calculations. '
   'GE internal use suspected — no documentation available.');


-- ─── XPS file type detection ──────────────────────────────────────────────────
-- XPS files are ZIP archives containing XAML pages exported from the BMD PC.
-- detect_xps_type() inspects XAML content to classify each file.
-- XPS is authoritative for BMD / T-score / Z-score.
-- MDB is authoritative for BMC, Area, and all patient demographics.

insert into bmd_metadata (category, key, label, confidence, notes) values
  ('xps_type', 'totalbody_bone',        'Total Body — Bone Density',  'confirmed',
   'Contains bone mineral density map for whole-body scan. Used for bone region images.'),
  ('xps_type', 'totalbody_composition', 'Total Body — Composition',   'confirmed',
   'Contains fat/lean distribution image and composition data. Used for fat/lean images.'),
  ('xps_type', 'totalbody_narrative',   'Total Body — Narrative Page', 'confirmed',
   'Text summary page from GE software. Not used for data extraction.'),
  ('xps_type', 'spine_femur',           'AP Spine + Femur (Osteo)',    'confirmed',
   'Spine and femur densitometry pages. Matched to osteo upload only. '
   'Authoritative source for T-scores and Z-scores used in osteo report.'),
  ('xps_type', 'unknown',               'Unknown / Unclassified',      'confirmed',
   'Could not determine type from XAML content. Not passed to any upload.');


-- ─── Pipeline quirks ──────────────────────────────────────────────────────────
-- Hard-won institutional knowledge about edge cases in the pipeline.

insert into bmd_metadata (category, key, label, confidence, notes) values
  ('pipeline_quirk', 'raw_json_double_stringified',
   'raw_json stored double-stringified in Supabase', 'confirmed',
   'bmd_scans.raw_json is a JSONB column but the Python worker inserts the value as a '
   'JSON string (i.e. a string containing JSON). To query as JSONB: '
   'SELECT (raw_json #>> ''{}'')::jsonb FROM bmd_scans;'),

  ('pipeline_quirk', 'totalbody_entry_detection',
   'Distinguish true total-body comp rows from osteo estimated rows', 'confirmed',
   'When a patient has both scan types, mdb_snapshot.composition contains entries for all '
   'img_handles. True total-body entry: bone_mass > 0 on label=7 row AND values in thousands (grams). '
   'Osteo estimated entry: bone_mass = 0 on label=7, values in hundreds (pct×10 scale). '
   'Parser uses isTotalbodyEntry() check on this rule.'),

  ('pipeline_quirk', 'combined_scan_patient_isolation',
   'Patients with both osteo and total-body scans must be scoped strictly', 'confirmed',
   'build_raw_osteo_json() filters to sessions where mdb_scan_type=osteo. '
   'collect_totalbody uses find_totalbody_img_handle() which searches scantype=10 only. '
   'Without this isolation the wrong session data bleeds into the wrong report type.'),

  ('pipeline_quirk', 'osteo_comp_scale',
   'Osteo estimated composition values are percentage×10, not grams', 'confirmed',
   'GE Lunar stores estimated body composition (from AP spine+femur) as fat_pct×10 in the '
   'same fat_mass column used for grams in total-body scans. '
   'e.g. fat_mass=398.5 means 39.85% fat, NOT 398.5 g. '
   'The osteo report uses fat_pct only — no kg or FMI derived from this.'),

  ('pipeline_quirk', 'xps_strict_matching',
   'XPS files must be strictly matched to scan type before upload', 'confirmed',
   'If XPS files exist but none match the required type (totalbody_* or spine_femur), '
   'the upload is blocked with a warning. No fallback to wrong-type XPS. '
   'User must export the correct scan from the BMD PC first.'),

  ('pipeline_quirk', 'bilateral_labels_not_on_all_scans',
   'Labels 51–58 (bilateral) absent on older or simplified scans', 'confirmed',
   'Some patients have only 6 composition rows (labels 1,2,3,7,59,60) with no bilateral breakdown. '
   'parseBilateral() returns null in this case and the symmetry card is hidden gracefully.'),

  ('pipeline_quirk', 'scantype0_dual_role',
   'scantype=0 used for both total-body and osteo spine', 'confirmed',
   'In an osteo session (no scantype=10), scantype=0 provides the AP spine densitometry. '
   'In a total-body session, scantype=0 also contains spine labels (19–22) within the '
   'total-body img. The parser picks the right context based on session composition.'),

  ('pipeline_quirk', 'multiple_pat_handles',
   'One patient MRN can have multiple pat_handle rows in MDB', 'confirmed',
   'GE Lunar creates a new pat_handle on re-registration or software reinstall. '
   'find_totalbody_img_handle() and build_raw_osteo_json() both search across all '
   'pat_handles matching the MRN to avoid missing scans after re-registration.');
