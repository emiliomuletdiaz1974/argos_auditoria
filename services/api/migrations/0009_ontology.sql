-- ARG-032 · Versioned RDF store of the normative ontology (deviation note ARG-031-033, ADR-0006).
-- Every published bundle keeps its own quads forever: the supervisor's question "which version
-- applied on 3 March?" is answered by the bundle whose in_force_from is the latest one not after
-- that date. The date comes from the signed manifest, never from the load time. Nothing here is
-- updated or deleted in place.
CREATE TABLE argos.ontology_bundles (
  version        text PRIMARY KEY CHECK (version ~ '^[0-9]+\.[0-9]+\.[0-9]+$'),
  sha256         text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  manifest       jsonb NOT NULL,
  signature      bytea NOT NULL,
  quads          integer NOT NULL CHECK (quads >= 0),
  in_force_from  date NOT NULL,
  loaded_at      timestamptz NOT NULL DEFAULT now()
);

-- Terms are stored in N3 form (IRIs, literals with language or datatype, blank node labels), so
-- a version graph is rebuilt exactly with rdflib.util.from_n3.
CREATE TABLE argos.ontology_quads (
  bundle  text NOT NULL REFERENCES argos.ontology_bundles(version),
  s       text NOT NULL,
  p       text NOT NULL,
  o       text NOT NULL
);
CREATE INDEX ix_ontology_quads_spo ON argos.ontology_quads (bundle, s, p);
CREATE INDEX ix_ontology_quads_pos ON argos.ontology_quads (bundle, p, md5(o));

CREATE FUNCTION argos.ontology_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'ontology bundles are immutable (% on %)', TG_OP, TG_TABLE_NAME;
END
$$;

CREATE TRIGGER ontology_bundles_immutable
  BEFORE UPDATE OR DELETE ON argos.ontology_bundles
  FOR EACH ROW EXECUTE FUNCTION argos.ontology_immutable();
CREATE TRIGGER ontology_bundles_no_truncate
  BEFORE TRUNCATE ON argos.ontology_bundles
  FOR EACH STATEMENT EXECUTE FUNCTION argos.ontology_immutable();
CREATE TRIGGER ontology_quads_immutable
  BEFORE UPDATE OR DELETE ON argos.ontology_quads
  FOR EACH ROW EXECUTE FUNCTION argos.ontology_immutable();
CREATE TRIGGER ontology_quads_no_truncate
  BEFORE TRUNCATE ON argos.ontology_quads
  FOR EACH STATEMENT EXECUTE FUNCTION argos.ontology_immutable();
