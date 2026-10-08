-- The printed dossier names what it talks about (2026-10-08): the systems audited and the elements
-- each finding is about, as the inventory calls them, instead of their ids. The evidence service
-- reads those names and nothing else of them: not the connection of a system, which holds the
-- reference to its secret, nor the categories of a node.
GRANT SELECT (id, name, kind) ON argos.systems TO svc_evidence;
GRANT SELECT (snapshot_id, node_key, name, qualified_name) ON argos.inventory_snapshot_nodes
  TO svc_evidence;
