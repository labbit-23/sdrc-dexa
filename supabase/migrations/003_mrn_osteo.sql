-- Migration 003: MRN support + osteo scan type + raw-osteo Storage bucket
-- Run against self-hosted Supabase after 002_bmd_tables.sql
--
-- Key changes:
--   1. Add mrn (Medical Record Number) to bmd_patients — this replaces the
--      old accession-number-based patient_id as the primary human identifier.
--      Staff enter the patient's MRN in the GE Lunar "Patient ID" field.
--   2. Add scan_type to bmd_scans ('osteo' | 'total_body') so trend reports
--      can distinguish spine/hip from whole-body scans.
--   3. Add image_paths JSONB to bmd_scans — Storage keys for the three PNG
--      images (spine, left_femur, right_femur) so the Next.js app can fetch
--      them from Supabase Storage without re-parsing XPS.
--   4. Raw-osteo Storage bucket declaration comment.

-- ── 1. MRN column on bmd_patients ──────────────────────────────────────────

alter table bmd_patients
  add column if not exists mrn text;           -- Medical Record Number

-- Unique index: one patient row per MRN (null rows excluded).
-- We allow null for legacy rows that pre-date MRN tracking.
create unique index if not exists bmd_patients_mrn_idx
  on bmd_patients(mrn) where mrn is not null;

comment on column bmd_patients.mrn is
  'Clinic Medical Record Number entered in GE Lunar "Patient ID" field. '
  'Primary key for trend tracking from 2026 onwards. '
  'patient_id retained for legacy accession-number rows.';

-- ── 2. scan_type on bmd_scans ──────────────────────────────────────────────

alter table bmd_scans
  add column if not exists scan_type text default 'osteo'
    check (scan_type in ('osteo', 'total_body'));

comment on column bmd_scans.scan_type is
  '''osteo'' = spine + hip DXA; ''total_body'' = whole-body composition scan.';

-- ── 3. image_paths on bmd_scans ────────────────────────────────────────────
-- Keys are Supabase Storage object paths (not public URLs) so the app can
-- construct signed or public URLs on demand.
-- Example:
--   { "spine": "raw-osteo/MRN123/20260513T103000Z/img_spine.png",
--     "left_femur": "raw-osteo/MRN123/20260513T103000Z/img_left_femur.png",
--     "right_femur": "raw-osteo/MRN123/20260513T103000Z/img_right_femur.png" }

alter table bmd_scans
  add column if not exists image_paths jsonb;

comment on column bmd_scans.image_paths is
  'Supabase Storage object paths for extracted scan images (PNG). '
  'Keys: spine, left_femur, right_femur (osteo) or fat_lean, fat_gradient, bone (total_body).';

-- ── 4. mrn index for fast patient lookup by MRN ────────────────────────────

create index if not exists bmd_scans_type_idx on bmd_scans(scan_type);

-- ── Storage buckets (run in Supabase dashboard → Storage, or via API) ──────
--
-- Bucket: raw-osteo  (private — contains raw XPS bytes and extracted PNGs)
--
--   insert into storage.buckets (id, name, public)
--   values ('raw-osteo', 'raw-osteo', false)
--   on conflict do nothing;
--
--   -- Service role can read/write; anon gets nothing.
--   create policy "osteo_service_rw" on storage.objects
--     for all using (bucket_id = 'raw-osteo' and auth.role() = 'service_role');
--
-- Bucket: bmd-pdfs   (public — generated PDF reports)
--
--   insert into storage.buckets (id, name, public)
--   values ('bmd-pdfs', 'bmd-pdfs', true)
--   on conflict do nothing;
--
--   create policy "bmd_public_read" on storage.objects
--     for select using (bucket_id = 'bmd-pdfs');
--
--   create policy "bmd_service_upload" on storage.objects
--     for insert with check (bucket_id = 'bmd-pdfs' and auth.role() = 'service_role');

-- ── Done ───────────────────────────────────────────────────────────────────
-- After running this migration, instruct staff to enter the patient MRN
-- (not the accession number) in the GE Lunar "Patient ID" field for all
-- new scans. The MRN will propagate through the MDB → collector → Supabase
-- pipeline automatically.
