-- SDRC DEXA BMD Report System — initial schema
-- Run against self-hosted Supabase instance

create extension if not exists "pgcrypto";

-- ─── patients ──────────────────────────────────────────────────────────────
create table patients (
  id            uuid primary key default gen_random_uuid(),
  pat_handle    text unique not null,   -- GE internal handle  e.g. pat_hq93dedu8cct
  patient_id    text,                   -- clinic ID           e.g. 20260323063
  first_name    text,
  last_name     text,                   -- used as title (MS / MRS / DR)
  dob           date,
  gender        text,                   -- 'Female' | 'Male'
  ethnicity     text,
  height_cm     numeric(5,1),
  weight_kg     numeric(5,1),
  physician     text,
  created_at    timestamptz default now(),
  updated_at    timestamptz default now()
);

create index on patients(patient_id);
create index on patients(lower(first_name));

-- ─── scan sessions ─────────────────────────────────────────────────────────
-- One row per GE "scan_handle" (a full scanning session that may include
-- total-body, left-femur, and right-femur img_handles).
create table scans (
  id              uuid primary key default gen_random_uuid(),
  patient_id      uuid references patients(id) on delete cascade,
  scan_handle     text unique not null,  -- GE scan_handle
  scan_date       timestamptz,
  scanner_serial  text,
  software        text,
  xps_filename    text,                  -- e.g. 20260323063.xps
  raw_json        jsonb,                 -- full parsed MDB + XPS data blob
  created_at      timestamptz default now()
);

create index on scans(patient_id);
create index on scans(scan_date desc);

-- ─── BMD results ───────────────────────────────────────────────────────────
create table bmd_results (
  id          uuid primary key default gen_random_uuid(),
  scan_id     uuid references scans(id) on delete cascade,
  site        text not null,   -- 'L1'|'L2'|'L3'|'L4'|'L1-L4'|'Neck'|'Wards'|'Trochanter'|'InterTroch'|'Total'
  side        text,            -- 'left' | 'right' | null (for spine)
  bmd         numeric(6,4),    -- g/cm²
  bmc         numeric(8,3),    -- grams
  area        numeric(7,3),    -- cm²
  t_score     numeric(5,2),
  z_score     numeric(5,2),
  pct_ya      numeric(6,2),    -- % Young Adult
  source      text default 'MDB',  -- 'XPS' | 'MDB'
  created_at  timestamptz default now()
);

create index on bmd_results(scan_id);
create index on bmd_results(scan_id, side, site);

-- ─── generated reports ─────────────────────────────────────────────────────
create table reports (
  id                uuid primary key default gen_random_uuid(),
  scan_id           uuid references scans(id) on delete cascade,
  pdf_path          text,        -- Supabase Storage path: pdfs/{patient_id}/{scan_date}.pdf
  pdf_url           text,        -- public URL
  generated_at      timestamptz default now(),
  generator_version text
);

create index on reports(scan_id);

-- ─── row-level security ────────────────────────────────────────────────────
-- Adjust policies for your auth setup.
-- For a single-clinic LAN deployment the simplest approach is to use the
-- service-role key on the worker and anon key (with permissive policy) on
-- the frontend.

alter table patients     enable row level security;
alter table scans        enable row level security;
alter table bmd_results  enable row level security;
alter table reports      enable row level security;

-- Permissive read for authenticated and anon users (LAN clinic, no PHI over internet)
create policy "read_all" on patients    for select using (true);
create policy "read_all" on scans       for select using (true);
create policy "read_all" on bmd_results for select using (true);
create policy "read_all" on reports     for select using (true);

-- Only service role (worker) can write
create policy "service_write" on patients    for all using (auth.role() = 'service_role');
create policy "service_write" on scans       for all using (auth.role() = 'service_role');
create policy "service_write" on bmd_results for all using (auth.role() = 'service_role');
create policy "service_write" on reports     for all using (auth.role() = 'service_role');

-- ─── storage ───────────────────────────────────────────────────────────────
-- Run these manually in the Supabase dashboard Storage section, or via API:
--
--   insert into storage.buckets (id, name, public)
--   values ('pdfs', 'pdfs', true);
--
--   create policy "public_read" on storage.objects for select using (bucket_id = 'pdfs');
--   create policy "service_write" on storage.objects for insert
--     with check (bucket_id = 'pdfs' and auth.role() = 'service_role');
