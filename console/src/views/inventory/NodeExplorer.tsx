// ARG-074 · one node of the graph: where it comes from, what it touches and what happened to it.
import { useResource } from "../../api/context";
import { DELTA_LABELS, when } from "./labels";

interface GraphNode {
  key: string;
  label: string;
  name: string | null;
  qualified_name: string | null;
  system_id: string | null;
}

interface Neighbour extends GraphNode {
  edge: string;
  direction: "in" | "out";
}

interface NodeDetail {
  node: GraphNode;
  props: Record<string, unknown>;
  neighbours: Neighbour[];
  has_more: boolean;
  deltas: Array<{ kind: string; at: string; run_id: string }>;
}

const nodePath = (key: string) => `/inventory/nodes/${encodeURIComponent(key)}`;
const title = (node: GraphNode) => node.qualified_name ?? node.name ?? node.key;

export function NodeExplorer({ nodeKey }: { nodeKey: string }) {
  const { data, error } = useResource<NodeDetail>(
    `/api/v1/inventory/nodes/${encodeURIComponent(nodeKey)}`,
  );
  if (error) {
    return (
      <p role="alert">
        {error.status === 404 ? "Ese nodo no existe en el inventario." : `Error: ${error.detail}`}
      </p>
    );
  }
  if (!data) {
    return <p className="muted">Cargando el nodo…</p>;
  }
  const source = data.props["source_connector"];
  return (
    <section className="panel node-explorer">
      <h2>{title(data.node)}</h2>
      <p className="muted">
        {data.node.label} · visto por primera vez {when(String(data.props["first_seen"] ?? ""))} ·
        visto por última vez {when(String(data.props["last_seen"] ?? ""))}
        {source ? ` · por ${String(source)}` : ""}
      </p>

      <h3>Vecindario</h3>
      <ul aria-label="Vecindario" className="neighbours">
        {data.neighbours.map((neighbour) => (
          <li key={`${neighbour.edge}-${neighbour.key}`}>
            <span className="muted">
              {neighbour.direction === "out" ? "→" : "←"} {neighbour.edge}
            </span>{" "}
            <a href={nodePath(neighbour.key)}>{title(neighbour)}</a>{" "}
            <span className="muted">({neighbour.label})</span>
          </li>
        ))}
      </ul>
      {data.has_more ? <p className="muted">Hay más vecinos de los que se muestran.</p> : null}

      <h3>Línea temporal</h3>
      <ol aria-label="Línea temporal" className="timeline">
        {data.deltas.length === 0 ? <li className="muted">Sin cambios registrados.</li> : null}
        {data.deltas.map((delta) => (
          <li key={`${delta.run_id}-${delta.kind}`}>
            {DELTA_LABELS[delta.kind] ?? delta.kind} · {when(delta.at)}
          </li>
        ))}
      </ol>
    </section>
  );
}
