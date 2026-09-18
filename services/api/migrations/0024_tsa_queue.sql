-- ARG-065 · Queue of objects waiting for an RFC 3161 time stamp.
--
-- An object enters when it is signed and stays 'queued', with its attempts and last error, until a
-- verified token exists; then it is 'stamped' and keeps where the token lives, its time and its
-- policy. The nonce of the last request is kept so a reply can be matched to it, online or brought
-- back from an isolated appliance. A stamped entry is final and no entry is ever removed.
CREATE TABLE argos.tsa_queue (
  object_key        text PRIMARY KEY CHECK (object_key <> ''),
  version_id        text NOT NULL CHECK (version_id <> ''),
  sha256            text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  status            text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'stamped')),
  attempts          integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  last_error        text,
  nonce             numeric(40, 0),
  enqueued_at       timestamptz NOT NULL DEFAULT now(),
  requested_at      timestamptz,
  exported_at       timestamptz,
  stamped_at        timestamptz,
  token_key         text,
  token_version_id  text,
  gen_time          timestamptz,
  policy            text,
  CHECK ((status = 'stamped') = (token_key IS NOT NULL AND token_version_id IS NOT NULL
                                  AND gen_time IS NOT NULL AND policy IS NOT NULL))
);
CREATE INDEX ix_tsa_queue_status ON argos.tsa_queue (status, enqueued_at);

CREATE FUNCTION argos.tsa_queue_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'UPDATE' AND OLD.status = 'queued' THEN
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'a stamped entry is final and no entry is removed (% on %)', TG_OP, TG_TABLE_NAME;
END
$$;

CREATE TRIGGER tsa_queue_guard
  BEFORE UPDATE OR DELETE ON argos.tsa_queue
  FOR EACH ROW EXECUTE FUNCTION argos.tsa_queue_guard();
CREATE TRIGGER tsa_queue_no_truncate
  BEFORE TRUNCATE ON argos.tsa_queue
  FOR EACH STATEMENT EXECUTE FUNCTION argos.campaign_write_once();
