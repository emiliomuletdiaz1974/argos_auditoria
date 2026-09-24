-- ARG-090 · normative content that comes in through the airlock (F09-13).
--
-- The airlock runs in the API: a content bundle on removable media is verified by `load_bundle`
-- (ARG-040: the pinned fingerprint, the signature, no rollback) and only then stored. Storing a
-- version writes its quads, so the API role, which could already record the bundle
-- (`ontology_bundles`), may now also insert its quads. Nothing else: no update, no delete (the
-- versioned store is append-only).
GRANT INSERT ON argos.ontology_quads TO svc_api;
