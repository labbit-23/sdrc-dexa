-- Tricog ECG: WhatsApp send-guard columns.
-- Purpose: let the Mirth channel check "has this already been sent to the
-- patient?" BEFORE sending, so a reprocess/retry/redeploy can never
-- automatically re-send a WhatsApp message that already went out.
-- A manual resend remains possible later (clearing these columns, or a
-- dedicated resend action) - this only blocks automatic re-sends.

alter table ecg_studies add column if not exists whatsapp_sent_at timestamptz;
alter table ecg_studies add column if not exists whatsapp_message_id text;

create index if not exists ecg_studies_whatsapp_sent_at_idx on ecg_studies(whatsapp_sent_at);
