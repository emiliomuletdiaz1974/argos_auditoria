-- ADR-0008 · Synthetic subjects: ARGOS generates and records them, the client injects them and
-- exercises the rights. Nothing here is a real person: every value is generated and marked (DNI in a
-- range that is never issued, IBAN with a fictitious entity, e-mail in example.invalid). The clear
-- values live only in the package handed to the client; the database keeps their hashes.
CREATE TABLE argos.synthetic_subjects (
  id            uuid PRIMARY KEY,
  campaign_id   uuid,
  seed          text NOT NULL,
  subject_index integer NOT NULL CHECK (subject_index >= 0),
  markers       jsonb NOT NULL,
  value_hashes  jsonb NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (seed, subject_index)
);

-- One row per authorised injection point. The client confirms each step, and every confirmation is
-- written once: a filled column is never overwritten (trigger below).
CREATE TABLE argos.synthetic_injections (
  id                      uuid PRIMARY KEY,
  subject_id              uuid NOT NULL REFERENCES argos.synthetic_subjects(id),
  system_id               uuid NOT NULL,
  point                   text NOT NULL,
  method                  text NOT NULL,
  revert_procedure        text NOT NULL,
  authorized_by           text NOT NULL,
  authorized_at           timestamptz NOT NULL DEFAULT now(),
  injected_confirmed_by   text,
  injected_at             timestamptz,
  exercised_right         text,
  exercised_confirmed_by  text,
  exercised_at            timestamptz,
  reverted_by             text,
  reverted_at             timestamptz,
  UNIQUE (subject_id, system_id, point)
);
CREATE INDEX ix_synthetic_injections_subject ON argos.synthetic_injections (subject_id);

CREATE FUNCTION argos.synthetic_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'synthetic injections are not deleted: revert them instead';
  END IF;
  IF NEW.subject_id <> OLD.subject_id OR NEW.system_id <> OLD.system_id
     OR NEW.point <> OLD.point OR NEW.method <> OLD.method
     OR NEW.authorized_by <> OLD.authorized_by OR NEW.authorized_at <> OLD.authorized_at
     OR NEW.revert_procedure <> OLD.revert_procedure THEN
    RAISE EXCEPTION 'the authorisation of a synthetic injection cannot change';
  END IF;
  IF (OLD.injected_confirmed_by IS NOT NULL AND NEW.injected_confirmed_by IS DISTINCT FROM OLD.injected_confirmed_by)
     OR (OLD.exercised_confirmed_by IS NOT NULL AND NEW.exercised_confirmed_by IS DISTINCT FROM OLD.exercised_confirmed_by)
     OR (OLD.reverted_by IS NOT NULL AND NEW.reverted_by IS DISTINCT FROM OLD.reverted_by) THEN
    RAISE EXCEPTION 'a confirmation of a synthetic injection is written once';
  END IF;
  RETURN NEW;
END
$$;

CREATE TRIGGER synthetic_injections_append_only
  BEFORE UPDATE OR DELETE ON argos.synthetic_injections
  FOR EACH ROW EXECUTE FUNCTION argos.synthetic_append_only();

CREATE FUNCTION argos.synthetic_subjects_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'synthetic subjects are immutable (% on %)', TG_OP, TG_TABLE_NAME;
END
$$;

CREATE TRIGGER synthetic_subjects_immutable
  BEFORE UPDATE OR DELETE ON argos.synthetic_subjects
  FOR EACH ROW EXECUTE FUNCTION argos.synthetic_subjects_immutable();
