// ARG-075 · the run as the workflow tells it, refreshed every five seconds while it lasts.
// A system paused by its circuit breaker is not a failure hidden in a log: it shows, with why.
import useSWR from "swr";

import { ApiError, useApi } from "../../api/context";

interface Progress {
  status: string;
  done: number;
  total?: number;
  findings: number;
  paused: Array<{ system_id: string; reason: string }>;
}

const REFRESH_MS = 5000;

export function LiveProgress({ campaignId }: { campaignId: string }) {
  const api = useApi();
  const { data, error } = useSWR<Progress, ApiError>(
    `/api/v1/campaigns/${campaignId}/progress`,
    async (path: string) => {
      const answer = await api(path);
      if (!answer.ok) {
        throw new ApiError(answer.status, "the campaign is not running");
      }
      return (await answer.json()) as Progress;
    },
    { refreshInterval: (latest) => (latest?.status === "sealed" ? 0 : REFRESH_MS) },
  );
  if (error) {
    return <p className="muted">La campaña no está en marcha.</p>;
  }
  if (!data) {
    return <p className="muted">Consultando el progreso…</p>;
  }
  const total = data.total ?? 0;
  return (
    <section className="panel" aria-label="Progreso">
      <h2>Progreso</h2>
      <progress aria-label="Unidades evaluadas" value={data.done} max={total || 1} aria-valuenow={data.done} aria-valuemax={total} />
      <p>
        {data.done} de {total} unidades · {data.findings} hallazgos · estado {data.status}
      </p>
      {data.paused.length > 0 ? (
        <>
          <h3>Sistemas en pausa</h3>
          <ul aria-label="Sistemas en pausa">
            {data.paused.map((system) => (
              <li key={system.system_id}>
                <code>{system.system_id}</code>
                {system.reason ? <span className="muted"> · {system.reason}</span> : null}
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </section>
  );
}
