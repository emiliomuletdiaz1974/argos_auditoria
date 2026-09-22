// ARG-077 · the artifacts of a campaign, page by page, each downloadable with the inclusion proof
// that places it under the signed root: a third party checks one without trusting the rest.
import { useState } from "react";

import { download, useApi, useResource, type ApiError } from "../../api/context";
import { when } from "../inventory/labels";

interface Artifact {
  verdict_id: string;
  sha256: string;
  created_at: string;
}

interface Page {
  items: Artifact[];
  next: string | null;
}

function ArtifactPage({
  campaignId,
  cursor,
  last,
  onMore,
  onDownload,
}: {
  campaignId: string;
  cursor: string | null;
  last: boolean;
  onMore: (cursor: string) => void;
  onDownload: (verdictId: string) => void;
}) {
  const query = cursor ? `?cursor=${encodeURIComponent(cursor)}` : "";
  const { data, error } = useResource<Page>(`/api/v1/evidence/${campaignId}/artifacts${query}`);
  if (error) {
    return (
      <tr>
        <td colSpan={4} role="alert">
          No se pudieron leer los artefactos: {error.detail}
        </td>
      </tr>
    );
  }
  if (!data) {
    return (
      <tr>
        <td colSpan={4} className="muted">
          Cargando…
        </td>
      </tr>
    );
  }
  return (
    <>
      {data.items.map((artifact) => (
        <tr key={artifact.verdict_id}>
          <td>
            <code>{artifact.verdict_id}</code>
          </td>
          <td>
            <code className="hash">{artifact.sha256}</code>
          </td>
          <td>{when(artifact.created_at)}</td>
          <td>
            <button type="button" onClick={() => onDownload(artifact.verdict_id)}>
              Descargar con su prueba de inclusión
            </button>
          </td>
        </tr>
      ))}
      {last && data.next ? (
        <tr>
          <td colSpan={4}>
            <button type="button" onClick={() => onMore(data.next ?? "")}>
              Más artefactos
            </button>
          </td>
        </tr>
      ) : null}
    </>
  );
}

export function ArtifactBrowser({ campaignId }: { campaignId: string }) {
  const api = useApi();
  const [cursors, setCursors] = useState<Array<string | null>>([null]);
  const [problem, setProblem] = useState<string | null>(null);

  const getOne = async (verdictId: string) => {
    setProblem(null);
    try {
      await download(api, `/api/v1/evidence/artifacts/${verdictId}`, `artefacto-${verdictId}.json`);
    } catch (failure) {
      setProblem((failure as ApiError).detail);
    }
  };

  return (
    <section className="panel" aria-label="Artefactos">
      <h2>Artefactos</h2>
      <table className="evidence-table">
        <thead>
          <tr>
            <th scope="col">Veredicto</th>
            <th scope="col">SHA-256</th>
            <th scope="col">Escrito</th>
            <th scope="col">Descarga</th>
          </tr>
        </thead>
        <tbody>
          {cursors.map((cursor, index) => (
            <ArtifactPage
              key={cursor ?? "first"}
              campaignId={campaignId}
              cursor={cursor}
              last={index === cursors.length - 1}
              onMore={(next) => setCursors([...cursors, next])}
              onDownload={(verdictId) => void getOne(verdictId)}
            />
          ))}
        </tbody>
      </table>
      {problem ? <p role="alert">{problem}</p> : null}
    </section>
  );
}
