-- Synthetic signals for the Phase 3 inventory ground truth (F03-00). Every value is generated:
-- DNI numbers use the 99990001-99991000 range, which is not issued; IBANs use the fictitious
-- bank code 9999; e-mail addresses use the reserved example.invalid domain.
CREATE TABLE clinic.patient_documents (
  patient_id      bigint PRIMARY KEY REFERENCES clinic.patients(id),
  dni_number      text NOT NULL,
  iban            text NOT NULL,
  diagnosis_code  text NOT NULL,
  email           text NOT NULL
);

INSERT INTO clinic.patient_documents
SELECT g,
       lpad((99990000 + g)::text, 8, '0')
         || substr('TRWAGMYFPDXBNJZSQVHLCKE', ((99990000 + g) % 23)::int + 1, 1),
       'ES'
         || lpad((98 - (('9999000100' || lpad(g::text, 10, '0') || '142800')::numeric % 97))::text, 2, '0')
         || '9999000100' || lpad(g::text, 10, '0'),
       (ARRAY['Z00.0', 'I10', 'E11.9', 'J45.909'])[1 + g % 4],
       'syn.patient' || g || '@example.invalid'
FROM generate_series(1, 1000) AS g;

CREATE TABLE clinic.readmission_risk (
  patient_id    bigint PRIMARY KEY REFERENCES clinic.patients(id),
  risk_score    numeric(4, 3) NOT NULL,
  predicted_at  timestamptz NOT NULL
);

INSERT INTO clinic.readmission_risk
SELECT g, ((g * 37) % 1000) / 1000.0, timestamptz '2026-01-01' + make_interval(hours => g)
FROM generate_series(1, 5000) AS g;

-- Declaration only: the link is never queried. It models an integration between the clinical and
-- billing systems for the engine-catalog flow detector (ARG-027).
CREATE EXTENSION postgres_fdw;
CREATE SERVER billing_link FOREIGN DATA WRAPPER postgres_fdw
  OPTIONS (host 'source-mariadb', port '3306', dbname 'billing');

ANALYZE clinic.patient_documents;
ANALYZE clinic.readmission_risk;

GRANT ALL ON clinic.patient_documents, clinic.readmission_risk TO clinic_admin;
GRANT SELECT ON clinic.patient_documents, clinic.readmission_risk TO argos_ro;
