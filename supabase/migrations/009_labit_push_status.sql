-- Migration 009: Labit push status on bmd_scans
-- Run against self-hosted Supabase after 008_ecg_pdf_plain.sql
--
-- Tracks whether a scan's report has been pushed to Labit Core, so the
-- patient list (/list) can show a "Pushed" indicator per scan instead of
-- staff having to remember or check Labit Core directly. Written by
-- sdrc-dexa-app's POST /api/labit-push on a successful (200) response —
-- never inferred, only recorded from an actual confirmed push.

alter table bmd_scans
  add column if not exists labit_pushed_at timestamptz;

comment on column bmd_scans.labit_pushed_at is
  'When this scan''s report was last successfully pushed to Labit Core. '
  'Null = never pushed. Updated (not just set once) on every successful '
  're-push, since Labit Core supersedes the prior attachment in place '
  'while it remains unapproved.';

alter table bmd_scans
  add column if not exists labit_test_ref text;

comment on column bmd_scans.labit_test_ref is
  'The comma-joined Labit testRef used for the most recent successful push '
  '(e.g. "BAP,BBH,BMW" for spine+both-hips+forearm, or "BWB" for total body). '
  'Kept alongside labit_pushed_at for display/debugging — not used by any '
  'query logic.';
