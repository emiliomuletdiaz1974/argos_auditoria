-- ARG-042 · A campaign resolves its applicability over the pinned snapshot, not over the live graph,
-- so two runs are comparable. The asset class of confirmed AI systems filters by `status`, which the
-- projection did not keep: without it the snapshot could not answer what the graph answers.
ALTER TABLE argos.inventory_snapshot_nodes ADD COLUMN status text;
