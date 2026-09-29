-- `argos.catalog_freshness` is a plain view: the functions it calls run with the privileges of whoever
-- reads it, not of its owner. Since 0033 nothing but the owner may execute `argos.agtype_text`, so
-- every service role that may SELECT the view failed on `SELECT * FROM argos.catalog_freshness`
-- with "permission denied for function agtype_text", and `GET /api/v1/inventory/coverage` answered
-- 503. `agtype_text` only reads a property of the value it is given, so it is granted, by name, to
-- the roles that read the view.
GRANT EXECUTE ON FUNCTION argos.agtype_text(ag_catalog.agtype, text)
  TO svc_api, svc_ai_gateway, svc_inventory, svc_backup;
