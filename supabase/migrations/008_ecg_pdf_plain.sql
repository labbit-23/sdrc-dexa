-- ECG: also store the plain (non-letterhead) PDF link.
-- pdf_url stays the SDRC-branded "_Graph" version used for WhatsApp/FTP;
-- pdf_url_plain is the original Tricog PDF, uploaded to FTP alongside it,
-- for a "Print" action that shouldn't double up SDRC's own letterhead.

alter table ecg_studies add column if not exists pdf_url_plain text;
