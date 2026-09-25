-- ARG-098 · the local series of the capacity of the appliance (F10-08).
--
-- One row per day and dimension: how much was used and what the size allowed. The health service
-- takes the snapshot once a day and keeps thirteen months; nothing of it leaves the appliance. The
-- API reads it for the capacity report.
CREATE TABLE argos.capacity_snapshots (
  taken_on   date NOT NULL,
  dimension  text NOT NULL
             CHECK (dimension IN ('systems', 'assets', 'parallel_campaigns', 'ai_tokens_per_day')),
  used       bigint NOT NULL CHECK (used >= 0),
  capacity   bigint NOT NULL CHECK (capacity > 0),
  size       text NOT NULL CHECK (size IN ('S', 'M', 'L')),
  PRIMARY KEY (taken_on, dimension)
);
REVOKE ALL ON argos.capacity_snapshots FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE, DELETE ON argos.capacity_snapshots TO svc_health;
GRANT SELECT ON argos.capacity_snapshots TO svc_api;
-- What the health service measures for it: the latest inventory snapshot, and the rest it reads.
GRANT SELECT ON argos.inventory_snapshots TO svc_health;

-- The API registers systems (POST /systems) and measures before it does: it reads what the four
-- dimensions count. It still deletes and updates no system.
GRANT INSERT ON argos.systems TO svc_api;
GRANT SELECT ON argos.inventory_snapshots, argos.campaigns, argos.ai_usage TO svc_api;
