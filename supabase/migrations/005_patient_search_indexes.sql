-- Run against the dedicated DEXA Supabase instance only.
-- Enables fast ilike search with leading wildcard on the patients table.

create extension if not exists pg_trgm;

create index if not exists patients_first_name_trgm_idx
  on patients using gin (first_name gin_trgm_ops);

create index if not exists patients_patient_id_trgm_idx
  on patients using gin (patient_id gin_trgm_ops);
