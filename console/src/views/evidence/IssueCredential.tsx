// ARG-077 · issuing the credential is an explicit act of the reviewer. The preview shows every
// field that travels, with its value, and what stays behind in the dossier; the issuance names the
// dossier it saw, so if it changed in between nothing is signed and the preview is read again.
// Only an accredited credential —not one signed with a development key— glows gold.
import { useState } from "react";

import { send, useApi, useResource, type ApiError } from "../../api/context";

interface Preview {
  dossier_sha256: string;
  credentialSubject: Record<string, unknown>;
  withheld: string[];
}

interface Issued {
  credential_id: string;
  revoked: boolean;
  credential: { credentialSubject: { nonProduction?: boolean } };
}

const WITHHELD_LABELS: Record<string, string> = {
  approvals: "Quién aprobó cada compuerta",
  "campaign.name": "El nombre de la campaña",
  "evidence_chain.artifacts": "Los artefactos de evidencia",
  findings: "Los hallazgos y dónde se encontraron",
  results_by_obligation: "Los resultados por obligación",
  texts: "Los textos redactados con asistencia",
};

const CONFLICT = 409;
const PREVIEW_REFUSALS: Record<number, string> = {
  403: "Emitir la credencial corresponde al revisor de protección de datos.",
  404: "La campaña todavía no tiene expediente: no hay credencial que emitir.",
};

function shown(value: unknown): string {
  return typeof value === "string" ? value : JSON.stringify(value);
}

function IssuedCredential({ issued }: { issued: Issued }) {
  if (issued.credential.credentialSubject.nonProduction ?? true) {
    return (
      <div className="panel" role="status">
        <p>
          <strong>Credencial de desarrollo</strong> · <code>{issued.credential_id}</code>
        </p>
        <p className="muted">Firmada con una clave de desarrollo: sirve para probar el circuito, no acredita nada.</p>
      </div>
    );
  }
  return (
    <div className="credential-seal" role="status">
      <p>
        <strong>Credencial emitida</strong> · <code>{issued.credential_id}</code>
      </p>
    </div>
  );
}

export function IssueCredential({ campaignId }: { campaignId: string }) {
  const api = useApi();
  const { data, error, mutate } = useResource<Preview>(`/api/v1/credentials/preview?campaign_id=${campaignId}`);
  const [reviewed, setReviewed] = useState(false);
  const [issued, setIssued] = useState<Issued | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  if (error) {
    return <p role="alert">{PREVIEW_REFUSALS[error.status] ?? error.detail}</p>;
  }
  if (!data) {
    return <p className="muted">Preparando la vista previa de la credencial…</p>;
  }
  if (issued) {
    return <IssuedCredential issued={issued} />;
  }

  const issue = async () => {
    setProblem(null);
    try {
      const answer = await send<Issued>(api, "/api/v1/credentials", {
        campaign_id: campaignId,
        dossier_sha256: data.dossier_sha256,
      });
      setIssued(answer);
    } catch (failure) {
      const refused = failure as ApiError;
      if (refused.status === CONFLICT) {
        setProblem("El expediente ha cambiado desde la vista previa. Revísala de nuevo antes de emitir.");
        setReviewed(false);
        await mutate();
        return;
      }
      setProblem(refused.detail);
    }
  };

  return (
    <section className="panel" aria-label="Credencial">
      <h2>Credencial verificable</h2>
      <table className="evidence-table" aria-label="Lo que viaja en la credencial">
        <caption>Lo que viaja en la credencial</caption>
        <tbody>
          {Object.entries(data.credentialSubject).map(([field, value]) => (
            <tr key={field}>
              <th scope="row">
                <code>{field}</code>
              </th>
              <td>
                <code>{shown(value)}</code>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <h3>Lo que se queda en el expediente</h3>
      <ul aria-label="Lo que no viaja">
        {data.withheld.map((field) => (
          <li key={field}>{WITHHELD_LABELS[field] ?? field}</li>
        ))}
      </ul>
      <label className="confirm">
        <input type="checkbox" checked={reviewed} onChange={(event) => setReviewed(event.target.checked)} />
        He revisado lo que viaja y lo que no, y quiero emitir la credencial de este expediente.
      </label>
      <div className="actions">
        <button type="button" className="btn-primary" disabled={!reviewed} onClick={() => void issue()}>
          Emitir la credencial
        </button>
      </div>
      {problem ? <p role="alert">{problem}</p> : null}
    </section>
  );
}
