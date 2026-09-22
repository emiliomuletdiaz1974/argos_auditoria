// ARG-075 · the gates of a campaign and their double control: who has approved, who is missing.
import { useState } from "react";

import { send, useApi, useResource, type ApiError } from "../../api/context";

interface Gate {
  gate: string;
  approvals: number;
  needed: number;
  approved_by: string[];
}

const GATE_LABELS: Record<string, string> = { start: "Arranque", sampling: "Muestreo" };

function missing(gate: Gate): string {
  const left = gate.needed - gate.approvals;
  if (left <= 0) {
    return "Aprobada";
  }
  if (gate.approvals === 0) {
    return left === 1 ? "Pendiente de aprobación" : `Faltan ${left} aprobaciones de personas distintas`;
  }
  return left === 1
    ? "Falta 1 aprobación de otra persona"
    : `Faltan ${left} aprobaciones de otras personas`;
}

export function GateTray({ campaignId }: { campaignId: string }) {
  const api = useApi();
  const { data, error, mutate } = useResource<{ items: Gate[] }>(`/api/v1/campaigns/${campaignId}/gates`);
  const [problem, setProblem] = useState<string | null>(null);

  const approve = async (gate: string) => {
    setProblem(null);
    try {
      await send(api, `/api/v1/campaigns/${campaignId}/gates/${gate}/approve`, {});
      await mutate();
    } catch (failure) {
      setProblem((failure as ApiError).detail);
    }
  };

  if (error) {
    return <p role="alert">No se pudieron leer las compuertas: {error.detail}</p>;
  }
  if (!data) {
    return <p className="muted">Cargando las compuertas…</p>;
  }
  if (data.items.length === 0) {
    return null;
  }
  return (
    <section className="panel" aria-label="Compuertas">
      <h2>Compuertas</h2>
      <ul className="gate-list">
        {data.items.map((gate) => {
          const label = GATE_LABELS[gate.gate] ?? gate.gate;
          const open = gate.approvals < gate.needed;
          return (
            <li key={gate.gate} aria-label={label} className="gate">
              <strong>{label}</strong> · {gate.approvals} de {gate.needed} · {missing(gate)}
              {gate.approved_by.length > 0 ? (
                <p className="muted">Con la aprobación de {gate.approved_by.join(", ")}</p>
              ) : null}
              {open ? (
                <button type="button" className="btn-primary" onClick={() => void approve(gate.gate)}>
                  Aprobar
                </button>
              ) : null}
            </li>
          );
        })}
      </ul>
      {problem ? <p role="alert">{problem}</p> : null}
    </section>
  );
}
