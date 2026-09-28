-- QA-31 (quality review QA-057): an answer that is not JSON —the support package, a PDF— is kept
-- as it was given, bytes and media type, so a retry with the same key receives the same file.
-- Before, storing it failed after the effect and left the key "running" for ever.
ALTER TABLE argos.api_idempotency
  ADD COLUMN response_body bytea,
  ADD COLUMN response_media_type text;
