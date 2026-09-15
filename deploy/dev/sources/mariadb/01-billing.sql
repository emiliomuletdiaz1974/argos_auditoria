-- Synthetic billing source for development (F02-04). Every value is generated; no real person.
CREATE TABLE billing.invoices (
  id            INT PRIMARY KEY,
  patient_ref   VARCHAR(16) NOT NULL,
  amount_cents  INT NOT NULL,
  issued_at     DATETIME NOT NULL,
  status        VARCHAR(12) NOT NULL
);

INSERT INTO billing.invoices (id, patient_ref, amount_cents, issued_at, status)
SELECT seq, CONCAT('SYN', LPAD(seq % 5000, 8, '0')), 1000 + (seq * 37) % 90000,
       TIMESTAMP('2010-01-01') + INTERVAL (seq * 5) HOUR, ELT(1 + seq % 3, 'paid', 'pending', 'void')
FROM seq_1_to_3000;

CREATE USER 'argos_ro'@'%' IDENTIFIED BY '';
GRANT SELECT ON billing.* TO 'argos_ro'@'%';
FLUSH PRIVILEGES;
