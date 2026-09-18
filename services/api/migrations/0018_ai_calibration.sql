-- ARG-055 · Calibration of the semantic classifier, learned from the DPO's decisions.
--
-- `ai_proposals` keeps what the model **declared** for each column. The review queue of ARG-025
-- keeps the calibrated confidence, because that is what the triage used; fitting the next curve on
-- it would feed the calibration its own output. So the declared value lives here, on the AI side,
-- and the refit joins both by column and category.
--
-- `ai_calibration` keeps one isotonic curve per category, refitted from the decided rows of the
-- queue. A category with fewer than 50 decisions has no row: the classifier then uses the identity
-- capped at 0.8, below the acceptance threshold, so an uncalibrated model can only queue.
CREATE TABLE argos.ai_proposals (
  node_key      text PRIMARY KEY,
  category      text NOT NULL,
  declared      numeric(5, 4) NOT NULL CHECK (declared >= 0 AND declared <= 1),
  calibrated    numeric(5, 4) NOT NULL CHECK (calibrated >= 0 AND calibrated <= 1),
  prompt_sha256 text NOT NULL CHECK (prompt_sha256 ~ '^[0-9a-f]{64}$'),
  proposed_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE argos.ai_calibration (
  category   text PRIMARY KEY,
  pairs      integer NOT NULL CHECK (pairs >= 0),
  curve      jsonb NOT NULL,
  fitted_at  timestamptz NOT NULL
);

GRANT SELECT, INSERT, UPDATE ON argos.ai_proposals, argos.ai_calibration TO argos_ai;
GRANT DELETE ON argos.ai_calibration TO argos_ai;
