// ARG-088 · support without remote access: the operator asks for a diagnostic package, reads the
// index and every file exactly as they would leave, and only then gets it encrypted for support.
import { useState } from "react";

import { download, send, useApi, useResource, type ApiError } from "../../api/context";
import "./support.css";

const BASE = "/api/v1/support/diagnostics";

interface PackageFile {
  name: string;
  size: number;
  sha256: string;
  scrubbed: number;
  content: string;
}

interface Diagnostics {
  id: string;
  status: "collecting" | "ready";
  index_sha256?: string;
  index?: { generated_at: string; note: string };
  files?: PackageFile[];
}

export function SupportView() {
  const api = useApi();
  const [id, setId] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  const ask = async () => {
    setProblem(null);
    try {
      const answer = await send<Diagnostics>(api, BASE, null);
      setId(answer.id);
    } catch (failure) {
      setProblem((failure as ApiError).detail);
    }
  };

  return (
    <div className="support-view">
      <section className="panel" aria-label="Diagnóstico">
        <h1>Diagnóstico para el soporte</h1>
        <p className="muted">
          ARGOS no abre ningún acceso remoto. Si el soporte necesita ver qué pasa, prepara aquí un paquete: lo lees
          entero antes de descargarlo, sale cifrado solo para la clave del soporte y lo envías tú por tu canal.
        </p>
        <button type="button" className="btn-primary" onClick={() => void ask()}>
          Preparar un paquete de diagnóstico
        </button>
        {problem ? <p role="alert">{problem}</p> : null}
      </section>
      {id ? <Review id={id} /> : null}
    </div>
  );
}

function Review({ id }: { id: string }) {
  const api = useApi();
  const path = `${BASE}/${id}`;
  // The collector runs next to the orchestrator: ask again every few seconds until it is ready.
  const { data, error } = useResource<Diagnostics>(path, {
    refreshInterval: (latest) => (latest?.status === "ready" ? 0 : 3000),
  });
  const [confirmed, setConfirmed] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  if (error) {
    return <p role="alert">{error.detail}</p>;
  }
  if (!data || data.status === "collecting" || !data.files || !data.index_sha256) {
    return (
      <p className="panel muted" role="status">
        Recogiendo el diagnóstico…
      </p>
    );
  }
  const sha = data.index_sha256;
  const files = data.files;

  const get = async () => {
    setProblem(null);
    try {
      await download(api, `${path}/package`, `argos-diagnostics-${id}.tar.gz.age`, {
        approved_index_sha256: sha,
      });
    } catch (failure) {
      setProblem((failure as ApiError).detail);
    }
  };

  return (
    <>
      <section className="panel" aria-label="Qué sale">
        <h2>Qué sale</h2>
        <p>{data.index?.note}</p>
        <p className="muted">
          Generado el {data.index?.generated_at}. Huella del índice: <code className="support-hash">{sha}</code>
        </p>
        <table className="support-index" aria-label="Índice del paquete">
          <caption>Índice del paquete</caption>
          <thead>
            <tr>
              <th scope="col">Fichero</th>
              <th scope="col">Tamaño</th>
              <th scope="col">Depuraciones</th>
            </tr>
          </thead>
          <tbody>
            {files.map((file) => (
              <tr key={file.name}>
                <td>{file.name}</td>
                <td>{file.size} bytes</td>
                <td>{file.scrubbed}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <section className="panel" aria-label="Contenido">
        <h2>Contenido, fichero a fichero</h2>
        {files.map((file) => (
          <details key={file.name} className="support-file" open>
            <summary>{file.name}</summary>
            <pre>{file.content}</pre>
          </details>
        ))}
      </section>
      <section className="panel" aria-label="Enviar">
        <label>
          <input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} /> He
          leído cada fichero y es lo que quiero enviar al soporte
        </label>
        <div className="actions">
          <button type="button" className="btn-primary" disabled={!confirmed} onClick={() => void get()}>
            Cifrar para el soporte y descargar
          </button>
        </div>
        {problem ? <p role="alert">{problem}</p> : null}
      </section>
    </>
  );
}
