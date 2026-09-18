-- ARG-052 · The AI role may append to the journal, and only append.
--
-- The gateway logs every completion in the chained journal (with the hash of the prompt, never the
-- prompt). Migration 0015 gave the `argos_ai` role its own tables but not the journal, and nothing
-- noticed because the tests of the gateway connected as the owner. Running it the way the container
-- does —under `argos_ai`— showed it: "permission denied for function journal_append".
--
-- `journal_append` is SECURITY DEFINER and is the only way into the journal, so this grants exactly
-- what is needed: append a chained entry. The table itself stays read-only for the role.
GRANT EXECUTE ON FUNCTION argos.journal_append(text, text, text) TO argos_ai;
