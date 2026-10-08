-- The printed dossier says who approved each gate by name, not by account id (2026-10-08). The name
-- is the one the token carried when approving (claim `name`), kept beside the approval because the
-- realm can change it later. It is for people to read: who approved is still `approved_by`, which
-- the seal, the separation of duties and the double control use. Approvals recorded before keep it
-- empty and the dossier shows them by a short account id.
ALTER TABLE argos.approvals ADD COLUMN approver_name text;
