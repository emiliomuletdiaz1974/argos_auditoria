-- Synthetic clinical source for development (F02-04). Every value is generated; no real person.
CREATE SCHEMA clinic;

CREATE TABLE clinic.patients (
  id           bigint PRIMARY KEY,
  national_id  text NOT NULL UNIQUE,
  full_name    text NOT NULL,
  birth_date   date NOT NULL,
  created_at   timestamptz NOT NULL
);
COMMENT ON TABLE clinic.patients IS 'Synthetic patients (personal data: identity)';

CREATE TABLE clinic.appointments (
  id          bigint PRIMARY KEY,
  patient_id  bigint NOT NULL REFERENCES clinic.patients(id),
  starts_at   timestamptz NOT NULL,
  department  text NOT NULL
);

CREATE TABLE clinic.consents (
  patient_id  bigint NOT NULL REFERENCES clinic.patients(id),
  purpose     text NOT NULL,
  granted     boolean NOT NULL,
  updated_at  timestamptz NOT NULL,
  PRIMARY KEY (patient_id, purpose)
);

INSERT INTO clinic.patients
SELECT g, 'SYN' || lpad(g::text, 8, '0'), 'Synthetic Person ' || g,
       date '1930-01-01' + (g * 7 % 32000), timestamptz '2003-01-01' + make_interval(days => g % 8000)
FROM generate_series(1, 5000) AS g;

INSERT INTO clinic.appointments
SELECT g, 1 + (g % 5000), timestamptz '2015-01-01' + make_interval(hours => g * 3),
       (ARRAY['radiology', 'cardiology', 'oncology', 'emergency'])[1 + g % 4]
FROM generate_series(1, 20000) AS g;

INSERT INTO clinic.consents
SELECT g, p, (g + length(p)) % 3 <> 0, timestamptz '2020-01-01' + make_interval(days => g % 1500)
FROM generate_series(1, 5000) AS g CROSS JOIN unnest(ARRAY['research', 'marketing']) AS p;

ANALYZE;

CREATE ROLE clinic_admin NOLOGIN;
GRANT ALL ON ALL TABLES IN SCHEMA clinic TO clinic_admin;

CREATE ROLE argos_ro LOGIN;
ALTER ROLE argos_ro SET default_transaction_read_only = on;
GRANT CONNECT ON DATABASE clinic TO argos_ro;
GRANT USAGE ON SCHEMA clinic TO argos_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA clinic TO argos_ro;
