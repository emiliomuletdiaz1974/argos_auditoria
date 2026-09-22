// ARG-077 · what a supervisor is handed: the dossier in JSON and PDF, and the bundle the public
// verifier checks without ARGOS. The API keeps in the journal who took which one.
import { useState } from "react";

import { download, useApi, type ApiError } from "../../api/context";

export function EvidenceDownloads({ campaignId }: { campaignId: string }) {
  const api = useApi();
  const [problem, setProblem] = useState<string | null>(null);
  const base = `/api/v1/evidence/${campaignId}`;

  const get = async (path: string, filename: string) => {
    setProblem(null);
    try {
      await download(api, `${base}/${path}`, filename);
    } catch (failure) {
      setProblem((failure as ApiError).detail);
    }
  };

  return (
    <section className="panel" aria-label="Descargas">
      <h2>Expediente y verificación</h2>
      <p className="muted">Cada descarga queda en el diario con quién la hizo y qué expediente se llevó.</p>
      <div className="actions">
        <button type="button" onClick={() => void get("dossier.json", `expediente-${campaignId}.json`)}>
          Expediente en JSON
        </button>
        <button type="button" onClick={() => void get("dossier.pdf", `expediente-${campaignId}.pdf`)}>
          Expediente en PDF
        </button>
        <button type="button" onClick={() => void get("bundle", `verificacion-${campaignId}.json`)}>
          Paquete de verificación para un tercero
        </button>
      </div>
      {problem ? <p role="alert">{problem}</p> : null}
    </section>
  );
}
