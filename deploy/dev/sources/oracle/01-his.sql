-- Synthetic HIS source for development (F02-04, heavy profile). Every value is generated.
ALTER SESSION SET CONTAINER = FREEPDB1;

CREATE TABLE his_owner.encounters (
  id           NUMBER PRIMARY KEY,
  patient_ref  VARCHAR2(16) NOT NULL,
  admitted_at  DATE NOT NULL,
  ward         VARCHAR2(20) NOT NULL
);

INSERT INTO his_owner.encounters
SELECT LEVEL, 'SYN' || LPAD(MOD(LEVEL, 5000), 8, '0'), DATE '2004-01-01' + MOD(LEVEL * 3, 7000),
       CASE MOD(LEVEL, 3) WHEN 0 THEN 'ICU' WHEN 1 THEN 'SURGERY' ELSE 'MATERNITY' END
FROM dual CONNECT BY LEVEL <= 2000;
COMMIT;

CREATE USER argos_ro IDENTIFIED BY "dev-only-ro";
GRANT CREATE SESSION TO argos_ro;
GRANT SELECT ON his_owner.encounters TO argos_ro;
GRANT SELECT_CATALOG_ROLE TO argos_ro;
GRANT AUDIT_VIEWER TO argos_ro;
