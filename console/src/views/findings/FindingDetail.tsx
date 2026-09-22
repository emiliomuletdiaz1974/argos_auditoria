// ARG-076 · one finding with its whole why, and only the moves the API says a person may make.
// The state machine lives in the domain: the console draws the transitions each finding brings and
// has no button that closes one. Closing is what the re-run does when the challenge passes again.
import { useState } from "react";

import { send, useApi, useResource, type ApiError } from "../../api/context";
import { percent, when } from "../inventory/labels";
import { AcceptRiskModal, type RiskAcceptance } from "./AcceptRiskModal";
import { ACTION_LABELS, HISTORY_LABELS, SEVERITY_LABELS, STATUS_LABELS } from "./labels";

const RISK_ACCEPTED = "risk_accepted";
const AWAITING_VERIFICATION = "pending_verification";

interface Sampling {
  population: number;
  sample: number;
  confidence: string;
  failures: number;
  projected_upper?: number;
  required_sample?: number;
}

interface HistoryStep {
  seq: number;
  at: string;
  actor: string;
  action: string;
  from: string | null;
  to: string | null;
  occurrences: number | null;
}

interface Finding {
  id: string;
  campaign_id: string;
  challenge_id: string;
  obligation: { id: string; norm: string | null; article: string | null; title: string | null };
  node_key: string;
  severity: string;
  status: string;
  occurrences: number;
  campaigns_seen: string[];
  risk_note: string | null;
  risk_expiry: string | null;
  verdict: {
    id: string;
    result: string;
    verdict: { detail?: Record<string, unknown> } | null;
    challenge_version: string;
    sampling: Sampling | null;
    probe_journal: { seq: number; action: string; at: string } | null;
  } | null;
  allowed_transitions: string[];
  history: HistoryStep[];
}

function shown(value: unknown): string {
  return typeof value === "string" ? value : JSON.stringify(value);
}

function Why({ finding }: { finding: Finding }) {
  const verdict = finding.verdict;
  const detail = verdict?.verdict?.detail ?? {};
  const sampling = verdict?.sampling;
  const probe = verdict?.probe_journal;
  const obligation = finding.obligation;
  return (
    <section className="panel" aria-label="Por qué">
      <h2>Por qué</h2>
      {"observed" in detail ? (
        <dl className="why">
          <dt>Criterio</dt>
          <dd>
            <code>{shown(detail.field)}</code> {shown(detail.operator)} <code>{shown(detail.expected)}</code>
          </dd>
          <dt>Se observó</dt>
          <dd>
            <code>{shown(detail.observed)}</code>
          </dd>
        </dl>
      ) : (
        <p className="muted">El veredicto no trae valores comparables.</p>
      )}
      {sampling ? (
        <p>
          Muestra de {sampling.sample} de {sampling.population} con confianza del{" "}
          {percent(Number(sampling.confidence) * 100)}: {sampling.failures} fallos en la muestra
          {sampling.projected_upper !== undefined ? `, hasta ${sampling.projected_upper} en la población` : ""}.
        </p>
      ) : (
        <p className="muted">Comprobación completa, sin muestreo.</p>
      )}
      {probe ? (
        <p>
          La consulta emitida está en el{" "}
          <a href={`/evidence/${finding.campaign_id}#journal-${probe.seq}`}>asiento {probe.seq} del diario</a> (
          <code>{probe.action}</code>, {when(probe.at)}).
        </p>
      ) : null}
      <p>
        <strong>{obligation.id}</strong>
        {obligation.norm ? ` · ${obligation.norm} · art. ${obligation.article ?? "—"}` : ""}
        {obligation.title ? <span className="muted"> · {obligation.title}</span> : null}
      </p>
    </section>
  );
}

function History({ steps }: { steps: HistoryStep[] }) {
  return (
    <section className="panel" aria-label="Historia del hallazgo">
      <h2>Historia</h2>
      <ol aria-label="Historia" className="history">
        {steps.map((step) => {
          const label =
            step.action === "finding.transition"
              ? (STATUS_LABELS[step.to ?? ""] ?? step.to)
              : (HISTORY_LABELS[step.action] ?? step.action);
          return (
            <li key={step.seq}>
              <strong>{label}</strong> · <code>{step.actor}</code> · {when(step.at)}
              {step.action === "finding.recur" && step.occurrences ? ` · ${step.occurrences}ª vez` : ""}
            </li>
          );
        })}
      </ol>
    </section>
  );
}

export function FindingDetail({ findingId }: { findingId: string }) {
  const api = useApi();
  const path = `/api/v1/findings/${findingId}`;
  const { data, error, mutate } = useResource<Finding>(path);
  const [accepting, setAccepting] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [rerun, setRerun] = useState<string | null>(null);

  if (error) {
    return <p role="alert">{error.status === 404 ? "Ese hallazgo no existe." : error.detail}</p>;
  }
  if (!data) {
    return <p className="muted">Cargando el hallazgo…</p>;
  }

  const act = async (action: () => Promise<unknown>) => {
    setProblem(null);
    try {
      await action();
      await mutate();
    } catch (failure) {
      setProblem((failure as ApiError).detail);
    }
  };
  const move = (to: string) => {
    if (to === RISK_ACCEPTED) {
      setAccepting(true);
      return;
    }
    void act(() => send(api, `${path}/transition`, { to }));
  };
  const accept = (acceptance: RiskAcceptance) => {
    setAccepting(false);
    void act(() => send(api, `${path}/transition`, { to: RISK_ACCEPTED, ...acceptance }));
  };
  const verify = () =>
    void act(async () => {
      const answer = await send<{ workflow_id?: string }>(api, `${path}/verify`, {});
      setRerun(answer.workflow_id ?? "");
    });

  return (
    <div className="finding-detail">
      <h1>{data.challenge_id}</h1>
      <p>
        <span className={`chip chip-${data.severity}`}>{SEVERITY_LABELS[data.severity] ?? data.severity}</span>{" "}
        {STATUS_LABELS[data.status] ?? data.status} · <code>{data.node_key}</code> ·{" "}
        {data.occurrences === 1 ? "visto 1 vez" : `visto ${data.occurrences} veces`}
      </p>
      {data.status === RISK_ACCEPTED ? (
        <p className="muted">
          Riesgo aceptado hasta {data.risk_expiry ?? "—"}: {data.risk_note}
        </p>
      ) : null}
      <Why finding={data} />
      <section className="panel" aria-label="Estado">
        <h2>Qué se puede hacer</h2>
        {data.status === AWAITING_VERIFICATION ? (
          <>
            <p>Solo la reejecución del reto puede cerrarlo, si ahora pasa, o reabrirlo, si no.</p>
            <button type="button" className="btn-primary" onClick={verify} disabled={rerun !== null}>
              Volver a ejecutar el reto
            </button>
            {rerun !== null ? <p role="status">Reejecución en marcha{rerun ? ` (${rerun})` : ""}.</p> : null}
          </>
        ) : null}
        {data.allowed_transitions.length > 0 ? (
          <div role="group" aria-label="Acciones" className="actions">
            {data.allowed_transitions.map((to) => (
              <button key={to} type="button" onClick={() => move(to)}>
                {ACTION_LABELS[to] ?? to}
              </button>
            ))}
          </div>
        ) : null}
        {data.allowed_transitions.length === 0 && data.status !== AWAITING_VERIFICATION ? (
          <p className="muted">No hay nada que una persona pueda hacer en este estado.</p>
        ) : null}
        {problem ? <p role="alert">{problem}</p> : null}
      </section>
      {data.history.length > 0 ? <History steps={data.history} /> : null}
      <AcceptRiskModal open={accepting} onAccept={accept} onCancel={() => setAccepting(false)} />
    </div>
  );
}
