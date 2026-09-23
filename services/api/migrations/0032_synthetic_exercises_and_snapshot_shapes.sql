-- ADR-0008 · ARG-042/049 · A right is measured with the client's dates, and coherence with the
-- campaign's snapshot (security review F09-02, SEC-014, SEC-015 and SEC-036).

-- One row per right exercised on an injection. The client declares when the request arrived and
-- when it was answered; the term is measured between the two, never between two console clicks.
-- A different right is another row, so a subject can exercise several without rewriting any.
CREATE TABLE argos.synthetic_exercises (
  id            uuid PRIMARY KEY,
  injection_id  uuid NOT NULL REFERENCES argos.synthetic_injections(id),
  exercised_right text NOT NULL CHECK (exercised_right IN ('access', 'erasure', 'rectification')),
  requested_at  timestamptz NOT NULL,
  answered_at   timestamptz NOT NULL CHECK (answered_at >= requested_at),
  confirmed_by  text NOT NULL,
  confirmed_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (injection_id, exercised_right)
);

CREATE FUNCTION argos.synthetic_exercises_immutable() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, argos AS $$
BEGIN
  RAISE EXCEPTION 'a confirmed exercise of a right is final (% on %)', TG_OP, TG_TABLE_NAME;
END
$$;

CREATE TRIGGER synthetic_exercises_immutable
  BEFORE UPDATE OR DELETE ON argos.synthetic_exercises
  FOR EACH ROW EXECUTE FUNCTION argos.synthetic_exercises_immutable();

-- The confirmations of an injection were written once by who confirmed, but their dates and the
-- right could still be rewritten. Now every filled column is final.
CREATE OR REPLACE FUNCTION argos.synthetic_append_only() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, argos AS $$
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
     OR (OLD.injected_at IS NOT NULL AND NEW.injected_at IS DISTINCT FROM OLD.injected_at)
     OR (OLD.exercised_right IS NOT NULL AND NEW.exercised_right IS DISTINCT FROM OLD.exercised_right)
     OR (OLD.exercised_confirmed_by IS NOT NULL AND NEW.exercised_confirmed_by IS DISTINCT FROM OLD.exercised_confirmed_by)
     OR (OLD.exercised_at IS NOT NULL AND NEW.exercised_at IS DISTINCT FROM OLD.exercised_at)
     OR (OLD.reverted_by IS NOT NULL AND NEW.reverted_by IS DISTINCT FROM OLD.reverted_by)
     OR (OLD.reverted_at IS NOT NULL AND NEW.reverted_at IS DISTINCT FROM OLD.reverted_at) THEN
    RAISE EXCEPTION 'a confirmation of a synthetic injection is written once';
  END IF;
  RETURN NEW;
END
$$;

-- A subject without a campaign escaped the check before the seal. Existing rows are left as they
-- are (NOT VALID): the rule holds for every subject registered from now on.
ALTER TABLE argos.synthetic_subjects
  ADD CONSTRAINT synthetic_subjects_campaign_required CHECK (campaign_id IS NOT NULL) NOT VALID;

-- What the coherence shapes validate, frozen with the snapshot: the same campaign always answers
-- the same, whatever the live graph does afterwards. N-Triples, one per line and sorted.
CREATE TABLE argos.inventory_snapshot_shapes_data (
  snapshot_id uuid PRIMARY KEY REFERENCES argos.inventory_snapshots(id),
  ntriples    text NOT NULL,
  sha256      text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TRIGGER inventory_snapshot_shapes_data_immutable
  BEFORE UPDATE OR DELETE ON argos.inventory_snapshot_shapes_data
  FOR EACH ROW EXECUTE FUNCTION argos.inventory_snapshot_immutable();
