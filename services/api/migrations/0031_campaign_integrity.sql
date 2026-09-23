-- ARG-043 · Once sealed, a campaign does not change (security review F09-02, SEC-016).
--
-- Verdicts were already write-once, but a sealed campaign still took new ones and its seal column
-- could be rewritten, so a campaign could be resealed after the fact with a new anchor. Now the
-- database refuses both, whoever the role.
CREATE FUNCTION argos.campaign_seal_is_final() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, argos AS $$
BEGIN
  IF OLD.seal IS NOT NULL AND NEW.seal IS DISTINCT FROM OLD.seal THEN
    RAISE EXCEPTION 'the seal of campaign % is final', OLD.id USING ERRCODE = 'integrity_constraint_violation';
  END IF;
  IF OLD.status = 'sealed' AND NEW.status IS DISTINCT FROM OLD.status THEN
    RAISE EXCEPTION 'campaign % is sealed', OLD.id USING ERRCODE = 'integrity_constraint_violation';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER campaign_seal_is_final BEFORE UPDATE ON argos.campaigns
  FOR EACH ROW EXECUTE FUNCTION argos.campaign_seal_is_final();

CREATE FUNCTION argos.no_verdict_after_seal() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, argos AS $$
BEGIN
  IF EXISTS (SELECT 1 FROM argos.campaigns WHERE id = NEW.campaign_id AND status = 'sealed') THEN
    RAISE EXCEPTION 'campaign % is sealed: no new verdict', NEW.campaign_id
      USING ERRCODE = 'integrity_constraint_violation';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER no_verdict_after_seal BEFORE INSERT ON argos.verdicts
  FOR EACH ROW EXECUTE FUNCTION argos.no_verdict_after_seal();
