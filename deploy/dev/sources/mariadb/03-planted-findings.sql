-- Planted finding for the Phase 5 campaign ground truth (F05-01): a billing account with read access
-- to the replica that holds health data, whose profile is not authorised for that category.
-- Idempotent, so it can also be applied to a running source.
CREATE USER IF NOT EXISTS 'billing_analyst'@'%' IDENTIFIED BY 'Dev-Only-Billing-2026';
GRANT SELECT ON billing.patient_mirror TO 'billing_analyst'@'%';
