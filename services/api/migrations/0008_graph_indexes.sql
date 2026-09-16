-- ARG-021/022 · Indexes Apache AGE 1.5.0 really uses on the inventory graph (task F03-15).
-- MATCH/MERGE with a property map ({key: $k}, {system_id: $s}) is planned as containment on the
-- agtype properties, which the btree on agtype_access_operator(key) from 0003 cannot serve, so each
-- lookup scanned the whole label (10 200 columns: 3.0 ms per lookup, quadratic inside UNWIND). A GIN
-- index on properties serves containment: 0.28 ms per lookup and 7 ms instead of 109 ms to upsert
-- ten columns. The btree stays: it enforces the unique natural key.
LOAD 'age';
SET LOCAL search_path = ag_catalog, "$user", public;

DO $do$
DECLARE
  label text;
BEGIN
  FOREACH label IN ARRAY ARRAY['System', 'Schema', 'Table', 'Column', 'FileArea', 'Identity',
                               'Group', 'AISystem', 'Treatment', 'Category'] LOOP
    EXECUTE format('CREATE INDEX %I ON inventory.%I USING gin (properties)',
                   'ix_inventory_' || lower(label) || '_properties', label);
  END LOOP;
END
$do$;
