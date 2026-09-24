// ARG-090 · the airlock of the isolated appliance: what the medium brought (each file verified by
// its own importer, with its result and its hash) and what may leave, from the closed list only.
import { useState } from "react";

import { send, useApi, type ApiError } from "../../api/context";
import "./airgap.css";

const KINDS = [
  { value: "tsq", label: "Peticiones de sello de tiempo (.tsq)" },
  { value: "dossier", label: "Expediente de una campaña" },
  { value: "credential", label: "Credencial de una campaña" },
  { value: "diagnostics", label: "Paquete de diagnóstico revisado" },
] as const;

interface ImportResult {
  file: string;
  kind: string | null;
  result: "imported" | "rejected";
  reason: string;
  sha256: string | null;
  size: number | null;
}

interface ExportResult {
  id: string;
  kind: string;
  files: { name: string; size: number; sha256: string }[];
}

export function AirgapView() {
  return (
    <div className="airgap-view">
      <section className="panel" aria-label="Esclusa">
        <h1>Esclusa de soportes</h1>
        <p className="muted">
          El appliance no tiene red: lo que entra y lo que sale pasa por aquí. Cada fichero que entra se verifica con su
          propia firma antes de aplicarse; solo salen los tipos de una lista cerrada. Todo queda en el diario.
        </p>
      </section>
      <Imports />
      <Exports />
    </div>
  );
}

function Imports() {
  const api = useApi();
  const [results, setResults] = useState<ImportResult[] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  const scan = async () => {
    setProblem(null);
    try {
      setResults((await send<{ results: ImportResult[] }>(api, "/api/v1/airgap/imports", null)).results);
    } catch (failure) {
      setProblem((failure as ApiError).detail);
    }
  };

  return (
    <section className="panel" aria-label="Entrada">
      <h2>Entrada</h2>
      <button type="button" className="btn-primary" onClick={() => void scan()}>
        Leer el soporte e importar lo que verifique
      </button>
      {problem ? <p role="alert">{problem}</p> : null}
      {results ? (
        results.length === 0 ? (
          <p className="muted">El soporte está vacío.</p>
        ) : (
          <table className="airgap-table" aria-label="Lo que trajo el soporte">
            <caption>Lo que trajo el soporte</caption>
            <thead>
              <tr>
                <th scope="col">Fichero</th>
                <th scope="col">Resultado</th>
                <th scope="col">Motivo</th>
                <th scope="col">SHA-256</th>
              </tr>
            </thead>
            <tbody>
              {results.map((row) => (
                <tr key={row.file}>
                  <td>{row.file}</td>
                  <td>{row.result === "imported" ? "Importado" : "Rechazado"}</td>
                  <td>{row.reason}</td>
                  <td className="airgap-hash">{row.sha256 ?? "sin leer"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )
      ) : null}
    </section>
  );
}

function Exports() {
  const api = useApi();
  const [kind, setKind] = useState<string>("tsq");
  const [campaign, setCampaign] = useState("");
  const [diagnostics, setDiagnostics] = useState("");
  const [approved, setApproved] = useState("");
  const [done, setDone] = useState<ExportResult | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  const write = async () => {
    setProblem(null);
    setDone(null);
    const body: Record<string, string> = { kind };
    if (kind === "dossier" || kind === "credential") body.campaign_id = campaign.trim();
    if (kind === "diagnostics") {
      body.diagnostics_id = diagnostics.trim();
      body.approved_index_sha256 = approved.trim();
    }
    try {
      setDone(await send<ExportResult>(api, "/api/v1/airgap/exports", body));
    } catch (failure) {
      setProblem((failure as ApiError).detail);
    }
  };

  return (
    <section className="panel" aria-label="Salida">
      <h2>Salida</h2>
      <label>
        Qué sale{" "}
        <select aria-label="Qué sale" value={kind} onChange={(event) => setKind(event.target.value)}>
          {KINDS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
      {kind === "dossier" || kind === "credential" ? (
        <label>
          Campaña <input value={campaign} onChange={(event) => setCampaign(event.target.value)} />
        </label>
      ) : null}
      {kind === "diagnostics" ? (
        <>
          <label>
            Paquete de diagnóstico <input value={diagnostics} onChange={(event) => setDiagnostics(event.target.value)} />
          </label>
          <label>
            Huella del índice revisado <input value={approved} onChange={(event) => setApproved(event.target.value)} />
          </label>
        </>
      ) : null}
      <div className="actions">
        <button type="button" className="btn-primary" onClick={() => void write()}>
          Escribir en el soporte
        </button>
      </div>
      {problem ? <p role="alert">{problem}</p> : null}
      {done ? (
        <table className="airgap-table" aria-label="Lo que se escribió">
          <caption>Escrito en {done.id}</caption>
          <thead>
            <tr>
              <th scope="col">Fichero</th>
              <th scope="col">Tamaño</th>
              <th scope="col">SHA-256</th>
            </tr>
          </thead>
          <tbody>
            {done.files.map((file) => (
              <tr key={file.name}>
                <td>{file.name}</td>
                <td>{file.size} bytes</td>
                <td className="airgap-hash">{file.sha256}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </section>
  );
}
