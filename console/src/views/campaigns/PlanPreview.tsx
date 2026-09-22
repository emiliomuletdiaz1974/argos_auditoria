// ARG-075 · the literal list of what is going to be asked, BEFORE anything runs.
// It is what makes the start gate signable: nobody else shows the probes before sending them.
import { useResource } from "../../api/context";

interface Unit {
  unit_id: string;
  challenge_id: string;
  obligation: string;
  node_key: string;
  severity: string;
  probe: { kind: string; target: string; statement: string | null };
}

interface Unverifiable {
  challenge_id: string;
  node_key: string;
  reason: string;
  system_id: string;
}

interface Plan {
  units: Unit[];
  unverifiable: Unverifiable[];
  probes_run: number;
}

function byObligation(units: Unit[]): Array<[string, Unit[]]> {
  const groups = new Map<string, Unit[]>();
  for (const unit of units) {
    groups.set(unit.obligation, [...(groups.get(unit.obligation) ?? []), unit]);
  }
  return [...groups.entries()].sort(([a], [b]) => a.localeCompare(b));
}

export function PlanPreview({ campaignId }: { campaignId: string }) {
  const { data, error } = useResource<Plan>(`/api/v1/campaigns/${campaignId}/plan`);
  if (error?.status === 409) {
    return (
      <p role="status" className="muted">
        Todavía no hay plan: aparece cuando la campaña se lanza y se detiene en la compuerta de
        arranque.
      </p>
    );
  }
  if (error) {
    return <p role="alert">No se pudo leer el plan: {error.detail}</p>;
  }
  if (!data) {
    return <p className="muted">Cargando el plan…</p>;
  }
  return (
    <section className="panel plan-preview" aria-label="Plan previo">
      <h2>Plan previo</h2>
      <p className="muted">
        {data.probes_run === 0
          ? "Ninguna sonda se ha ejecutado todavía: esto es lo que se va a preguntar, literalmente."
          : `${data.probes_run} sondas ejecutadas.`}
      </p>
      {byObligation(data.units).map(([obligation, units]) => (
        <details key={obligation} className="plan-group" role="group" aria-label={obligation} open>
          <summary>
            <strong>{obligation}</strong> <span className="chip">{units.length} comprobaciones</span>
          </summary>
          <table className="plan-table">
            <thead>
              <tr>
                <th scope="col">Reto</th>
                <th scope="col">Destino</th>
                <th scope="col">Pregunta</th>
              </tr>
            </thead>
            <tbody>
              {units.map((unit) => (
                <tr key={unit.unit_id}>
                  <td>
                    <code>{unit.challenge_id}</code>
                  </td>
                  <td>{unit.probe.target}</td>
                  <td>
                    <code>{unit.probe.statement ?? `(${unit.probe.kind})`}</code>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      ))}
      {data.unverifiable.length > 0 ? (
        <section className="plan-unverifiable" aria-label="No verificable">
          <h3>No verificable ({data.unverifiable.length})</h3>
          <ul>
            {data.unverifiable.map((item) => (
              <li key={`${item.challenge_id}-${item.node_key}`}>
                <code>{item.challenge_id}</code> sobre <code>{item.node_key}</code>:{" "}
                <span className="muted">{item.reason}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </section>
  );
}
