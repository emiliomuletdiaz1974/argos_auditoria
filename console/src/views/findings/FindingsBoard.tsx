// ARG-076 · the triage: worst first, as the API orders it, with filters that live in the address
// so a reload or a shared link keeps them.
import { useState } from "react";

import { useResource } from "../../api/context";
import { when } from "../inventory/labels";
import { SEVERITY_LABELS, STATUS_LABELS } from "./labels";

export const FINDING_PREFIX = "/findings/";

interface FindingRow {
  id: string;
  challenge_id: string;
  obligation: string;
  node_key: string;
  severity: string;
  status: string;
  occurrences: number;
  updated_at: string;
}

type Filters = { severity: string; status: string };

function readFilters(): Filters {
  const query = new URLSearchParams(window.location.search);
  return { severity: query.get("severity") ?? "", status: query.get("status") ?? "" };
}

function queryOf(filters: Filters): string {
  const query = new URLSearchParams();
  if (filters.severity) {
    query.set("severity", filters.severity);
  }
  if (filters.status) {
    query.set("status", filters.status);
  }
  const text = query.toString();
  return text ? `?${text}` : "";
}

export function FindingsBoard() {
  const [filters, setFilters] = useState<Filters>(readFilters);
  const { data, error } = useResource<{ items: FindingRow[] }>(`/api/v1/findings${queryOf(filters)}`);

  const change = (name: keyof Filters, value: string) => {
    const next = { ...filters, [name]: value };
    setFilters(next);
    window.history.replaceState(null, "", `${window.location.pathname}${queryOf(next)}`);
  };

  return (
    <section className="panel" aria-label="Hallazgos">
      <h1>Hallazgos</h1>
      <div className="filters">
        <label>
          Severidad
          <select value={filters.severity} onChange={(event) => change("severity", event.target.value)}>
            <option value="">Todas</option>
            {Object.entries(SEVERITY_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Estado
          <select value={filters.status} onChange={(event) => change("status", event.target.value)}>
            <option value="">Todos</option>
            {Object.entries(STATUS_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
      </div>
      {error ? <p role="alert">No se pudieron leer los hallazgos: {error.detail}</p> : null}
      {!data && !error ? <p className="muted">Cargando los hallazgos…</p> : null}
      {data && data.items.length === 0 ? <p className="muted">Ningún hallazgo con estos filtros.</p> : null}
      {data && data.items.length > 0 ? (
        <table className="findings-table">
          <thead>
            <tr>
              <th scope="col">Severidad</th>
              <th scope="col">Reto</th>
              <th scope="col">Obligación</th>
              <th scope="col">Recurrencia</th>
              <th scope="col">Estado</th>
              <th scope="col">Actualizado</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((finding) => (
              <tr key={finding.id}>
                <td>
                  <span className={`chip chip-${finding.severity}`}>
                    {SEVERITY_LABELS[finding.severity] ?? finding.severity}
                  </span>
                </td>
                <td>
                  <a href={`${FINDING_PREFIX}${finding.id}`}>{finding.challenge_id}</a>
                  <div className="muted">
                    <code>{finding.node_key}</code>
                  </div>
                </td>
                <td>{finding.obligation}</td>
                <td>{finding.occurrences === 1 ? "1 vez" : `${finding.occurrences} veces`}</td>
                <td>{STATUS_LABELS[finding.status] ?? finding.status}</td>
                <td>{when(finding.updated_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </section>
  );
}
