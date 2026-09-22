// ARG-074 · the review queue: a person decides what the model only proposed.
// Each decision corrects the graph and is also the label the calibration of ARG-055 learns from:
// the button teaches the system.
import { useState } from "react";

import { send, useApi, useResource, type ApiError } from "../../api/context";
import { CATEGORY_LABELS } from "./labels";

interface Pending {
  node_key: string;
  qualified_name: string;
  proposed_category: string;
  confidence: number;
  reason: string;
}

interface Queue {
  items: Pending[];
  next: string | null;
}

type Decision = { decision: "accept" } | { decision: "reject" } | { decision: "correct"; category: string };

function Row({ item, onDecided }: { item: Pending; onDecided: () => void }) {
  const api = useApi();
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [correction, setCorrection] = useState(
    Object.keys(CATEGORY_LABELS).find((c) => c !== item.proposed_category) ?? "",
  );

  const decide = async (decision: Decision) => {
    setBusy(true);
    setProblem(null);
    try {
      await send(api, `/api/v1/inventory/review-queue/${encodeURIComponent(item.node_key)}`, decision);
      onDecided();
    } catch (error) {
      setProblem((error as ApiError).detail);
    } finally {
      setBusy(false);
    }
  };

  const selectId = `correct-${item.node_key}`;
  return (
    <article className="review-row" aria-label={item.qualified_name}>
      <div>
        <code>{item.qualified_name}</code>
        <p className="muted">
          Propuesta: <span className="chip">{CATEGORY_LABELS[item.proposed_category] ?? item.proposed_category}</span>{" "}
          confianza {Math.round(item.confidence * 100)} % · {item.reason}
        </p>
      </div>
      <div className="review-actions">
        <button type="button" className="btn-primary" disabled={busy} onClick={() => void decide({ decision: "accept" })}>
          Confirmar
        </button>
        <label htmlFor={selectId}>Corregir a</label>
        <select id={selectId} value={correction} onChange={(event) => setCorrection(event.target.value)}>
          {Object.entries(CATEGORY_LABELS)
            .filter(([id]) => id !== item.proposed_category)
            .map(([id, label]) => (
              <option key={id} value={id}>
                {label}
              </option>
            ))}
        </select>
        <button
          type="button"
          className="btn-secondary"
          disabled={busy || !correction}
          onClick={() => void decide({ decision: "correct", category: correction })}
        >
          Corregir
        </button>
        <button type="button" className="btn-secondary" disabled={busy} onClick={() => void decide({ decision: "reject" })}>
          Rechazar
        </button>
      </div>
      {problem ? <p role="alert">{problem}</p> : null}
    </article>
  );
}

export function ReviewQueue() {
  const { data, error, mutate } = useResource<Queue>("/api/v1/inventory/review-queue");
  if (error) {
    return <p role="alert">No se pudo leer la cola: {error.detail}</p>;
  }
  if (!data) {
    return <p className="muted">Cargando la cola de revisión…</p>;
  }
  return (
    <section className="panel review-queue" aria-label="Cola de revisión">
      <h2>
        Cola de revisión <span className="chip">{data.items.length} pendientes</span>
      </h2>
      {data.items.length === 0 ? <p className="muted">No hay columnas pendientes de revisar.</p> : null}
      {data.items.map((item) => (
        <Row key={item.node_key} item={item} onDecided={() => void mutate()} />
      ))}
    </section>
  );
}
