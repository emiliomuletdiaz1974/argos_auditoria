-- Synthetic ERP source for development (F02-04, heavy profile). Every value is generated.
IF DB_ID('erp') IS NOT NULL SET NOEXEC ON;
GO
CREATE DATABASE erp;
GO
ALTER DATABASE erp SET ALLOW_SNAPSHOT_ISOLATION ON;
GO
USE erp;
GO
CREATE TABLE dbo.staff (
  id         INT PRIMARY KEY,
  username   NVARCHAR(40) NOT NULL,
  role_name  NVARCHAR(40) NOT NULL,
  active     BIT NOT NULL,
  hired_at   DATE NOT NULL
);
GO
WITH n AS (
  SELECT TOP (500) ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) AS i
  FROM sys.all_objects a CROSS JOIN sys.all_objects b
)
INSERT INTO dbo.staff
SELECT i, CONCAT('syn.user', i),
       CASE i % 4 WHEN 0 THEN 'admin' WHEN 1 THEN 'nurse' WHEN 2 THEN 'doctor' ELSE 'clerk' END,
       CASE WHEN i % 9 = 0 THEN 0 ELSE 1 END, DATEADD(day, i * 11, '2005-01-01')
FROM n;
GO
CREATE LOGIN argos_ro WITH PASSWORD = 'Dev-Only-Ro-2026';
CREATE USER argos_ro FOR LOGIN argos_ro;
ALTER ROLE db_datareader ADD MEMBER argos_ro;
GO
USE master;
GO
GRANT VIEW SERVER STATE TO argos_ro;
GRANT VIEW ANY DEFINITION TO argos_ro;
CREATE SERVER AUDIT argos_dev_audit TO FILE (FILEPATH = '/var/opt/mssql/data/');
ALTER SERVER AUDIT argos_dev_audit WITH (STATE = ON);
GO
SET NOEXEC OFF;
GO
