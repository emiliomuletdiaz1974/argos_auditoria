-- Synthetic mirror of clinic.patient_documents for the structural flow detector (F03-00).
-- Same generated values as the PostgreSQL source: DNI range 99990001-99991000 (not issued),
-- fictitious bank code 9999, reserved example.invalid domain.
CREATE TABLE billing.patient_mirror (
  id              INT PRIMARY KEY,
  dni_number      VARCHAR(9) NOT NULL,
  iban            VARCHAR(24) NOT NULL,
  diagnosis_code  VARCHAR(10) NOT NULL,
  email           VARCHAR(64) NOT NULL
);

INSERT INTO billing.patient_mirror (id, dni_number, iban, diagnosis_code, email)
SELECT seq,
       CONCAT(LPAD(99990000 + seq, 8, '0'),
              SUBSTRING('TRWAGMYFPDXBNJZSQVHLCKE', MOD(99990000 + seq, 23) + 1, 1)),
       CONCAT('ES',
              LPAD(98 - MOD(CAST(CONCAT('9999000100', LPAD(seq, 10, '0'), '142800') AS DECIMAL(38, 0)), 97), 2, '0'),
              '9999000100', LPAD(seq, 10, '0')),
       ELT(1 + MOD(seq, 4), 'Z00.0', 'I10', 'E11.9', 'J45.909'),
       CONCAT('syn.patient', seq, '@example.invalid')
FROM seq_1_to_1000;
