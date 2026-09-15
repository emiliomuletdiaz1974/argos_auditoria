-- ARG-021 · Inventory graph on Apache AGE 1.5.0: closed vocabulary, unique natural keys and the
-- root categories (deviation note ARG-021-023). AGE creates no index on label tables by itself.
CREATE EXTENSION IF NOT EXISTS age;
LOAD 'age';
SET LOCAL search_path = ag_catalog, "$user", public;

SELECT create_graph('inventory');

SELECT create_vlabel('inventory', 'System');
SELECT create_vlabel('inventory', 'Schema');
SELECT create_vlabel('inventory', 'Table');
SELECT create_vlabel('inventory', 'Column');
SELECT create_vlabel('inventory', 'FileArea');
SELECT create_vlabel('inventory', 'Identity');
SELECT create_vlabel('inventory', 'Group');
SELECT create_vlabel('inventory', 'AISystem');
SELECT create_vlabel('inventory', 'Treatment');
SELECT create_vlabel('inventory', 'Category');

SELECT create_elabel('inventory', 'CONTAINS');
SELECT create_elabel('inventory', 'CAN_ACCESS');
SELECT create_elabel('inventory', 'MEMBER_OF');
SELECT create_elabel('inventory', 'FLOWS_TO');
SELECT create_elabel('inventory', 'CLASSIFIED_AS');
SELECT create_elabel('inventory', 'DECLARED_IN');
SELECT create_elabel('inventory', 'USES_MODEL');
SELECT create_elabel('inventory', 'OBSERVED');

-- One natural key per node: MERGE stays idempotent even with concurrent writers.
DO $do$
DECLARE
  label text;
BEGIN
  FOREACH label IN ARRAY ARRAY['System', 'Schema', 'Table', 'Column', 'FileArea', 'Identity',
                               'Group', 'AISystem', 'Treatment', 'Category'] LOOP
    EXECUTE format(
      'CREATE UNIQUE INDEX %I ON inventory.%I USING btree '
      '(agtype_access_operator(VARIADIC ARRAY[properties, %L::agtype]))',
      'uq_inventory_' || lower(label) || '_key', label, '"key"');
    EXECUTE format('CREATE INDEX %I ON inventory.%I (id)',
                   'ix_inventory_' || lower(label) || '_id', label);
  END LOOP;
  FOREACH label IN ARRAY ARRAY['CONTAINS', 'CAN_ACCESS', 'MEMBER_OF', 'FLOWS_TO', 'CLASSIFIED_AS',
                               'DECLARED_IN', 'USES_MODEL', 'OBSERVED'] LOOP
    EXECUTE format('CREATE INDEX %I ON inventory.%I (start_id)',
                   'ix_inventory_' || lower(label) || '_start', label);
    EXECUTE format('CREATE INDEX %I ON inventory.%I (end_id)',
                   'ix_inventory_' || lower(label) || '_end', label);
  END LOOP;
END
$do$;

-- Root categories; key = natural_key("K", name) (argos_inventory.graph.model.category_key).
SELECT * FROM cypher('inventory', $q$
  MERGE (:Category {key: '54b6680e6aff9247b4e52ba175386903bc650514', name: 'personal_data'})
$q$) AS (v agtype);
SELECT * FROM cypher('inventory', $q$
  MERGE (:Category {key: '5a18981911f00fa070193002ae2777d85baa1d8a', name: 'special_category.health'})
$q$) AS (v agtype);
SELECT * FROM cypher('inventory', $q$
  MERGE (:Category {key: 'fc86fd7e1fd09795295df38da1e1ebf988631fb5', name: 'special_category.other'})
$q$) AS (v agtype);
SELECT * FROM cypher('inventory', $q$
  MERGE (:Category {key: '6fec3552e5abb3ca30e04e33474d1df8a2e64be2', name: 'official_identifier'})
$q$) AS (v agtype);
SELECT * FROM cypher('inventory', $q$
  MERGE (:Category {key: '3f373297b3233722fea225eab14c9e4a4978d4ac', name: 'financial_data'})
$q$) AS (v agtype);
SELECT * FROM cypher('inventory', $q$
  MERGE (:Category {key: 'ebc7c1790733f4762c63b0fe9e7bb2e9fe1b531b', name: 'contact_data'})
$q$) AS (v agtype);
SELECT * FROM cypher('inventory', $q$
  MERGE (:Category {key: '31daee5b235974ef00cfcba5293d1c893715920e', name: 'location_data'})
$q$) AS (v agtype);
SELECT * FROM cypher('inventory', $q$
  MERGE (:Category {key: 'ffa3a453947e16adf73f420d4c05e3dfdf133562', name: 'technical_credential'})
$q$) AS (v agtype);
SELECT * FROM cypher('inventory', $q$
  MERGE (:Category {key: '7b2b04ccfe0491ef435338277a8351e5981df24b', name: 'no_personal_data'})
$q$) AS (v agtype);
