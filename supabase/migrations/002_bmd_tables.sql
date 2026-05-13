-- SDRC DEXA BMD tables — safe to run against an existing Supabase instance.
-- All tables are prefixed bmd_ to avoid collisions with other products.

create extension if not exists "pgcrypto";

-- ─── bmd_patients ──────────────────────────────────────────────────────────
create table if not exists bmd_patients (
  id            uuid primary key default gen_random_uuid(),
  pat_handle    text unique not null,
  patient_id    text,
  first_name    text,
  last_name     text,
  dob           date,
  gender        text,
  ethnicity     text,
  height_cm     numeric(5,1),
  weight_kg     numeric(5,1),
  physician     text,
  created_at    timestamptz default now(),
  updated_at    timestamptz default now()
);

create index if not exists bmd_patients_patient_id_idx on bmd_patients(patient_id);
create index if not exists bmd_patients_name_idx      on bmd_patients(lower(first_name));

-- ─── bmd_scans ─────────────────────────────────────────────────────────────
create table if not exists bmd_scans (
  id              uuid primary key default gen_random_uuid(),
  patient_id      uuid references bmd_patients(id) on delete cascade,
  scan_handle     text unique not null,
  scan_date       timestamptz,
  scanner_serial  text,
  software        text,
  xps_filename    text,
  raw_json        jsonb,
  created_at      timestamptz default now()
);

create index if not exists bmd_scans_patient_id_idx on bmd_scans(patient_id);
create index if not exists bmd_scans_date_idx       on bmd_scans(scan_date desc);

-- ─── bmd_results ───────────────────────────────────────────────────────────
create table if not exists bmd_results (
  id          uuid primary key default gen_random_uuid(),
  scan_id     uuid references bmd_scans(id) on delete cascade,
  site        text not null,
  side        text,
  bmd         numeric(6,4),
  bmc         numeric(8,3),
  area        numeric(7,3),
  t_score     numeric(5,2),
  z_score     numeric(5,2),
  pct_ya      numeric(6,2),
  source      text default 'MDB',
  created_at  timestamptz default now()
);

create index if not exists bmd_results_scan_id_idx      on bmd_results(scan_id);
create index if not exists bmd_results_scan_site_idx    on bmd_results(scan_id, side, site);

-- ─── bmd_reports ───────────────────────────────────────────────────────────
create table if not exists bmd_reports (
  id                uuid primary key default gen_random_uuid(),
  scan_id           uuid references bmd_scans(id) on delete cascade,
  pdf_path          text,
  pdf_url           text,
  generated_at      timestamptz default now(),
  generator_version text
);

create index if not exists bmd_reports_scan_id_idx on bmd_reports(scan_id);

-- ─── RLS ───────────────────────────────────────────────────────────────────
alter table bmd_patients enable row level security;
alter table bmd_scans     enable row level security;
alter table bmd_results   enable row level security;
alter table bmd_reports   enable row level security;

-- Any authenticated or anon user can read (LAN clinic, no PHI over internet)
create policy "bmd_read_all" on bmd_patients for select using (true);
create policy "bmd_read_all" on bmd_scans    for select using (true);
create policy "bmd_read_all" on bmd_results  for select using (true);
create policy "bmd_read_all" on bmd_reports  for select using (true);

-- Only the service role (Python worker) can write
create policy "bmd_service_write" on bmd_patients for all using (auth.role() = 'service_role');
create policy "bmd_service_write" on bmd_scans    for all using (auth.role() = 'service_role');
create policy "bmd_service_write" on bmd_results  for all using (auth.role() = 'service_role');
create policy "bmd_service_write" on bmd_reports  for all using (auth.role() = 'service_role');

-- ─── Storage bucket (run in Supabase dashboard or via API) ─────────────────
-- insert into storage.buckets (id, name, public) values ('bmd-pdfs', 'bmd-pdfs', true);
-- create policy "bmd_public_read"    on storage.objects for select using (bucket_id = 'bmd-pdfs');
-- create policy "bmd_service_upload" on storage.objects for insert
--   with check (bucket_id = 'bmd-pdfs' and auth.role() = 'service_role');
