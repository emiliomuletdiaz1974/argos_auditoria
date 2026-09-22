// ARG-077 · the journal entry a finding points to (`#journal-<seq>`): the question ARGOS asked, as
// the journal keeps it. Only entries cited by a verdict of this campaign are served.
import { useEffect } from "react";

import { useResource } from "../../api/context";
import { when } from "../inventory/labels";

interface Entry {
  seq: number;
  at: string;
  actor: string;
  action: string;
  payload: unknown;
  entry_hash: string;
}

export function JournalEntry({ campaignId, seq }: { campaignId: string; seq: number }) {
  const { data, error } = useResource<Entry>(`/api/v1/evidence/${campaignId}/journal/${seq}`);

  useEffect(() => {
    if (data) {
      document.getElementById(`journal-${seq}`)?.scrollIntoView?.({ block: "center" });
    }
  }, [data, seq]);

  if (error) {
    return (
      <p role="alert">
        {error.status === 404 ? `Ningún veredicto de esta campaña cita el asiento ${seq}.` : error.detail}
      </p>
    );
  }
  if (!data) {
    return <p className="muted">Leyendo el asiento {seq} del diario…</p>;
  }
  return (
    <section id={`journal-${seq}`} className="panel journal-entry" aria-label={`Asiento ${seq} del diario`}>
      <h2>Asiento {seq} del diario</h2>
      <dl className="why">
        <dt>Acción</dt>
        <dd>
          <code>{data.action}</code>
        </dd>
        <dt>Instante</dt>
        <dd>{when(data.at)}</dd>
        <dt>Actor</dt>
        <dd>
          <code>{data.actor}</code>
        </dd>
        <dt>Hash del asiento</dt>
        <dd>
          <code className="hash">{data.entry_hash}</code>
        </dd>
      </dl>
      <pre className="payload">{JSON.stringify(data.payload, null, 2)}</pre>
    </section>
  );
}
