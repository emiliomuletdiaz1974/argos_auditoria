// ARG-092/099 · the operation screen: the eight lights of the appliance, the alerts Alertmanager
// delivered and, for each one, the runbook that says what to do. The state of a light is written in
// words as well as in colour, and a light nobody measures says so instead of looking green.
import { useState } from "react";

import { useResource } from "../../api/context";
import { Markdown } from "./Markdown";
import "./operations.css";

interface Light {
  key: string;
  title: string;
  state: "green" | "red" | "unknown";
  value: number | null;
  text?: string | null;
}

interface Alert {
  alertname: string;
  severity: string;
  summary: string;
  runbook: string | null;
  labels: Record<string, string>;
  starts_at: string | null;
}

interface Status {
  lights: Light[];
  alerts: Alert[];
  measured: boolean;
}

const STATE_WORDS: Record<Light["state"], string> = { green: "Correcto", red: "Fallo", unknown: "Sin medir" };
const SEVERITY_WORDS: Record<string, string> = { critical: "Crítica", warning: "Aviso" };

export function OperationsView() {
  const { data, error } = useResource<Status>("/api/v1/operations/status", { refreshInterval: 30_000 });
  const [runbook, setRunbook] = useState<string | null>(null);

  if (error) {
    return <p role="alert">{error.detail}</p>;
  }
  if (!data) {
    return <p className="muted">Cargando el estado del appliance…</p>;
  }
  return (
    <div className="operations-view">
      <section className="panel" aria-label="Estado del appliance">
        <h1>Operación</h1>
        {data.measured ? (
          <ul className="lights" aria-label="Semáforos">
            {data.lights.map((light) => (
              <li key={light.key} className={`light light-${light.state}`}>
                <span className="light-title">{light.title}</span>
                <span className="light-state">{light.key === "version" ? (light.text ?? "—") : STATE_WORDS[light.state]}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">Esta API no está conectada a Prometheus: no hay semáforos que mostrar.</p>
        )}
      </section>
      <section className="panel" aria-label="Alertas">
        <h2>Alertas activas</h2>
        {data.alerts.length === 0 ? (
          <p className="muted">No hay ninguna alerta activa.</p>
        ) : (
          <table aria-label="Alertas activas">
            <thead>
              <tr>
                <th>Alerta</th>
                <th>Severidad</th>
                <th>Qué pasa</th>
                <th>Runbook</th>
              </tr>
            </thead>
            <tbody>
              {data.alerts.map((alert) => (
                <tr key={`${alert.alertname}-${JSON.stringify(alert.labels)}`}>
                  <td>{alert.alertname}</td>
                  <td>{SEVERITY_WORDS[alert.severity] ?? alert.severity}</td>
                  <td>{alert.summary}</td>
                  <td>
                    {alert.runbook ? (
                      <button type="button" className="btn-link" onClick={() => setRunbook(alert.runbook)}>
                        {alert.runbook.slice(0, 5)}
                      </button>
                    ) : (
                      "—"
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
      <Capacity />
      {runbook ? <Runbook id={runbook} /> : null}
    </div>
  );
}

interface Usage {
  dimension: string;
  used: number;
  limit: number;
  ratio: number;
  band: "green" | "amber" | "red";
}

const DIMENSION_WORDS: Record<string, string> = {
  systems: "Sistemas registrados",
  assets: "Activos del inventario",
  parallel_campaigns: "Campañas en paralelo",
  ai_tokens_per_day: "Tokens de IA en 24 h",
};
const BAND_WORDS: Record<Usage["band"], string> = {
  green: "Holgado",
  amber: "Cerca del límite",
  red: "En el límite",
};

// ARG-098 · where the appliance stands against its size: the same bands the API refuses with.
function Capacity() {
  const { data } = useResource<{ size: string; usage: Usage[] }>("/api/v1/operations/capacity");
  if (!data) {
    return null;
  }
  return (
    <section className="panel" aria-label="Capacidad">
      <h2>Capacidad (talla {data.size})</h2>
      <table aria-label="Capacidad">
        <thead>
          <tr>
            <th>Dimensión</th>
            <th>Uso</th>
            <th>Franja</th>
          </tr>
        </thead>
        <tbody>
          {data.usage.map((row) => (
            <tr key={row.dimension} className={`band-${row.band}`}>
              <td>{DIMENSION_WORDS[row.dimension] ?? row.dimension}</td>
              <td>{`${row.used.toLocaleString("es-ES")} de ${row.limit.toLocaleString("es-ES")}`}</td>
              <td>{BAND_WORDS[row.band]}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function Runbook({ id }: { id: string }) {
  const { data, error } = useResource<{ id: string; markdown: string }>(`/api/v1/operations/runbooks/${id}`);
  if (error) {
    return <p role="alert">{error.detail}</p>;
  }
  if (!data) {
    return <p className="muted">Cargando el runbook…</p>;
  }
  return (
    <section className="panel runbook" aria-label={`Runbook ${id}`}>
      <Markdown text={data.markdown} />
    </section>
  );
}
