-- ARG-026 · Relational projection of the inventory graph for the console and the inventory sign-off
-- (P-26), deviation note ARG-026-028. AGE 1.5.0 properties are read with agtype_access_operator:
-- properties->>'x' and a cast of the whole agtype to jsonb do not work.
-- The graphid "=" used to join vertices and edges lives in ag_catalog: the views are parsed with it
-- in the search path and keep the resolved operators afterwards.
LOAD 'age';
SET LOCAL search_path = ag_catalog, "$user", public;

CREATE FUNCTION argos.agtype_text(properties ag_catalog.agtype, name text) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT ag_catalog.agtype_access_operator(
    VARIADIC ARRAY[properties, ('"' || name || '"')::ag_catalog.agtype])::text
$$;

CREATE MATERIALIZED VIEW argos.catalog_columns AS
SELECT
  argos.agtype_text(s.properties, 'id')                              AS system_id,
  argos.agtype_text(s.properties, 'name')                            AS system_name,
  argos.agtype_text(h.properties, 'name')                            AS schema_name,
  argos.agtype_text(t.properties, 'name')                            AS table_name,
  argos.agtype_text(c.properties, 'name')                            AS column_name,
  argos.agtype_text(c.properties, 'qualified_name')                  AS qualified_name,
  argos.agtype_text(c.properties, 'key')                             AS column_key,
  coalesce(argos.agtype_text(c.properties, 'missing')::boolean, false) AS missing,
  coalesce(argos.agtype_text(k.properties, 'name'), 'unclassified')  AS category,
  argos.agtype_text(r.properties, 'method')                          AS method,
  argos.agtype_text(r.properties, 'confidence')::float               AS confidence
FROM inventory."System" s
JOIN inventory."CONTAINS" e1 ON e1.start_id = s.id
JOIN inventory."Schema" h    ON h.id = e1.end_id
JOIN inventory."CONTAINS" e2 ON e2.start_id = h.id
JOIN inventory."Table" t     ON t.id = e2.end_id
JOIN inventory."CONTAINS" e3 ON e3.start_id = t.id
JOIN inventory."Column" c    ON c.id = e3.end_id
LEFT JOIN inventory."CLASSIFIED_AS" r ON r.start_id = c.id
LEFT JOIN inventory."Category" k      ON k.id = r.end_id;

CREATE UNIQUE INDEX uq_catalog_columns ON argos.catalog_columns (column_key, category);
CREATE INDEX ix_catalog_columns_system ON argos.catalog_columns (system_id);

CREATE MATERIALIZED VIEW argos.catalog_coverage AS
SELECT
  system_id,
  max(system_name)                                                            AS system_name,
  count(DISTINCT column_key)                                                  AS columns_total,
  count(DISTINCT column_key) FILTER (WHERE category <> 'unclassified')        AS columns_classified,
  round(100.0 * count(DISTINCT column_key) FILTER (WHERE category <> 'unclassified')
        / nullif(count(DISTINCT column_key), 0), 1)                           AS coverage_pct,
  count(DISTINCT column_key) FILTER (WHERE category LIKE 'special_category.%') AS special_columns,
  count(DISTINCT column_key) FILTER (WHERE method = 'dict')                   AS dict_columns,
  count(DISTINCT column_key) FILTER (WHERE method LIKE 'validator:%')         AS validator_columns,
  count(DISTINCT column_key) FILTER (WHERE method = 'ai')                     AS ai_columns,
  count(DISTINCT column_key) FILTER (WHERE method = 'human')                  AS human_columns
FROM argos.catalog_columns
WHERE NOT missing
GROUP BY system_id;

CREATE UNIQUE INDEX uq_catalog_coverage ON argos.catalog_coverage (system_id);

-- Freshness depends on now(): a plain view over the registered systems and their scan runs.
CREATE VIEW argos.catalog_freshness AS
SELECT
  s.id                        AS system_id,
  s.name,
  s.kind,
  s.owner,
  s.owner IS NOT NULL         AS has_owner,
  run.finished_at             AS last_scan_at,
  run.status                  AS last_scan_status,
  round((extract(epoch FROM now() - run.finished_at) / 3600.0)::numeric, 1) AS hours_since_scan,
  coalesce(gone.assets, 0)    AS missing_assets
FROM argos.systems s
LEFT JOIN LATERAL (
  SELECT r.finished_at, r.status FROM argos.scan_runs r
  WHERE r.system_id = s.id AND r.finished_at IS NOT NULL
  ORDER BY r.finished_at DESC LIMIT 1
) run ON true
LEFT JOIN LATERAL (
  SELECT count(*)::integer AS assets
  FROM (
    SELECT properties FROM inventory."Table"
    UNION ALL SELECT properties FROM inventory."Column"
    UNION ALL SELECT properties FROM inventory."FileArea"
  ) a
  WHERE argos.agtype_text(a.properties, 'system_id') = s.id::text
    AND argos.agtype_text(a.properties, 'missing') = 'true'
) gone ON true;

CREATE FUNCTION argos.refresh_catalog() RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
  REFRESH MATERIALIZED VIEW CONCURRENTLY argos.catalog_columns;
  REFRESH MATERIALIZED VIEW CONCURRENTLY argos.catalog_coverage;
END
$$;
