-- SDRC Tricog ECG tables — safe to run against an existing Supabase instance.
-- Table is prefixed ecg_ to avoid collisions with other products (bmd_, etc).
--
-- One row per ECG study. Unlike BMD (which splits patients/scans/results
-- because a single scan session covers multiple sites with multiple
-- measurements each), a Tricog ECG is a single study with a single report,
-- so it doesn't need the same split — mirrors bmd_scans.raw_json in keeping
-- the full source payload alongside the extracted fields.

create extension if not exists "pgcrypto";

-- ─── ecg_studies ───────────────────────────────────────────────────────────
create table if not exists ecg_studies (
  id                    uuid primary key default gen_random_uuid(),
  accession_no          text not null,          -- SDRC requisition/accession number (Tricog's patientId)
  tricog_ecg_id         text unique not null,   -- Tricog's ecgId (GUID)
  patient_name          text,
  age                   int,
  sex                   text,
  branch_center_id      text,                   -- Tricog centerId for the SDRC branch
  branch_center_name    text,
  diagnosis             text,
  final_classification  text,
  status                text,
  acquired_at           timestamptz,
  pdf_url               text,                   -- public FTP link uploaded by the Mirth channel
  source                text default 'TRICOG',
  raw_json              jsonb,                  -- full Tricog record + delivery metadata
  created_at            timestamptz default now(),
  updated_at            timestamptz default now()
);

create index if not exists ecg_studies_accession_no_idx  on ecg_studies(accession_no);
create index if not exists ecg_studies_acquired_at_idx   on ecg_studies(acquired_at desc);
create index if not exists ecg_studies_patient_name_idx  on ecg_studies(lower(patient_name));

-- ─── RLS ───────────────────────────────────────────────────────────────────
alter table ecg_studies enable row level security;

-- Any authenticated or anon user can read (LAN clinic, no PHI over internet)
create policy "ecg_read_all" on ecg_studies for select using (true);

-- Only the service role (Mirth channel, via SUPABASE_SERVICE_KEY) can write
create policy "ecg_service_write" on ecg_studies for all using (auth.role() = 'service_role');
