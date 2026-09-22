// ARG-074 · «what is there and how much do I know of it»: the map, a node, and the review queue.
import "./inventory.css";

import { InventoryMap } from "./InventoryMap";
import { NodeExplorer } from "./NodeExplorer";
import { ReviewQueue } from "./ReviewQueue";

export const NODE_PREFIX = "/inventory/nodes/";

export function InventoryView({ path }: { path: string }) {
  if (path.startsWith(NODE_PREFIX)) {
    return <NodeExplorer nodeKey={decodeURIComponent(path.slice(NODE_PREFIX.length))} />;
  }
  return (
    <>
      <h1>Inventario</h1>
      <InventoryMap />
      <ReviewQueue />
    </>
  );
}
