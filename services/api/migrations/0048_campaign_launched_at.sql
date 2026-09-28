-- QA-32 (quality review QA-006): a campaign takes its place among the parallel ones from the moment
-- it is launched, not from the moment its workflow asks for the first gate. Until then it stayed
-- `planned` or `pinned` without a request, and launches one after the other passed the limit.
ALTER TABLE argos.campaigns ADD COLUMN launched_at timestamptz;
