// ARG-074 · the map: one card per system, the coverage as the big number.
// Special-category data is flagged with the amber of severity, never with gold: gold is only for
// what is accredited.
import { useResource } from "../../api/context";
import { percent, when } from "./labels";

interface SystemCoverage {
  system_id: string;
  system_name: string;
  coverage_pct: number | null;
  columns_total: number;
  special_columns: number;
  missing_assets: number;
  pending_review: number;
  last_scan_at: string | null;
}

interface Coverage {
  systems: SystemCoverage[];
}

export function InventoryMap() {
  const { data, error } = useResource<Coverage>("/api/v1/inventory/coverage");
  if (error) {
    return <p role="alert">No se pudo leer la cobertura: {error.detail}</p>;
  }
  if (!data) {
    return <p className="muted">Cargando el inventario…</p>;
  }
  return (
    <section aria-label="Mapa del inventario" className="inventory-map">
      {data.systems.map((system) => (
        <article key={system.system_id} className="panel system-card" aria-label={system.system_name}>
          <h2>{system.system_name}</h2>
          <p className="coverage-figure">{percent(system.coverage_pct)}</p>
          <p className="muted">
            de {system.columns_total} columnas clasificadas · última exploración {when(system.last_scan_at)}
          </p>
          <ul className="system-flags">
            {system.special_columns > 0 ? (
              <li className="chip chip-high">
                {system.special_columns} columnas de categoría especial
              </li>
            ) : null}
            {system.missing_assets > 0 ? (
              <li className="chip chip-low">{system.missing_assets} nodos desaparecidos</li>
            ) : null}
            {system.pending_review > 0 ? (
              <li className="chip">{system.pending_review} pendientes de revisión</li>
            ) : null}
          </ul>
        </article>
      ))}
    </section>
  );
}
