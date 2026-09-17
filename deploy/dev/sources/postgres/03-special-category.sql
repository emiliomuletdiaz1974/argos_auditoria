-- Synthetic special category other than health (GDPR art. 9.1): trade union membership of staff.
-- Every value is generated; the union names are fictitious. Idempotent, so it can also be applied to
-- a running source: psql -h 127.0.0.1 -p 55433 -U owner -d clinic -f 03-special-category.sql
CREATE TABLE IF NOT EXISTS clinic.staff_affiliations (
  staff_id     bigint PRIMARY KEY,
  trade_union  text NOT NULL,
  joined_on    date NOT NULL
);

INSERT INTO clinic.staff_affiliations
SELECT g,
       (ARRAY['Sindicato Sintetico A', 'Sindicato Sintetico B', 'Sindicato Sintetico C'])[1 + g % 3],
       date '2000-01-01' + (g * 13 % 9000)
FROM generate_series(1, 300) AS g
ON CONFLICT (staff_id) DO NOTHING;

ANALYZE clinic.staff_affiliations;

GRANT ALL ON clinic.staff_affiliations TO clinic_admin;
GRANT SELECT ON clinic.staff_affiliations TO argos_ro;
