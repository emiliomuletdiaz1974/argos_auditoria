// ARG-077 · the evidence chain link by link, said as it is. A stamp still in the queue is in the
// queue; a signature made with a development key is a development signature. Nothing here glows
// gold: gold belongs to the accredited verdict and the credential, not to a chain being built.
import type { ReactNode } from "react";

import { useResource } from "../../api/context";
import { when } from "../inventory/labels";

interface Chain {
  artifacts: Array<{ verdict_id: string }>;
  merkle: { root: string; leaf_count: number } | null;
  signature: { sha256: string; key_id: string; non_production: boolean } | null;
  time_stamp: { status: string; gen_time: string | null; policy: string | null } | null;
  journal_report: { sha256: string } | null;
}

const QUEUED = "queued";

function Link({ name, state, children }: { name: string; state: "ok" | "partial" | "missing"; children: ReactNode }) {
  return (
    <li aria-label={name} className={`chain-link chain-${state}`}>
      <strong>{name}</strong>
      <div>{children}</div>
    </li>
  );
}

export function EvidenceChain({ campaignId }: { campaignId: string }) {
  const { data, error } = useResource<Chain>(`/api/v1/evidence/${campaignId}/chain`);
  if (error) {
    return <p role="alert">No se pudo leer la cadena de evidencia: {error.detail}</p>;
  }
  if (!data) {
    return <p className="muted">Leyendo la cadena de evidencia…</p>;
  }
  const { artifacts, merkle, signature, time_stamp: stamp, journal_report: journal } = data;
  return (
    <section className="panel" aria-label="Cadena de evidencia">
      <h2>Cadena de evidencia</h2>
      <ol aria-label="Eslabones" className="chain">
        <Link name="Artefactos" state={artifacts.length > 0 ? "ok" : "missing"}>
          <span>{artifacts.length === 1 ? "1 artefacto" : `${artifacts.length} artefactos`}</span> en el almacén WORM
        </Link>
        <Link name="Raíz de Merkle" state={merkle ? "ok" : "missing"}>
          {merkle ? (
            <>
              <span>Raíz de {merkle.leaf_count} hojas</span> · <code className="hash">{merkle.root}</code>
            </>
          ) : (
            "Todavía no hay raíz: la campaña no se ha cerrado."
          )}
        </Link>
        <Link name="Firma" state={!signature ? "missing" : signature.non_production ? "partial" : "ok"}>
          {!signature
            ? "Sin firmar."
            : signature.non_production
              ? `Firmada con una clave de desarrollo (${signature.key_id}): no vale fuera de las pruebas.`
              : `Firmada con la clave ${signature.key_id}.`}
        </Link>
        <Link name="Sello de tiempo" state={!stamp ? "missing" : stamp.status === QUEUED ? "partial" : "ok"}>
          {!stamp
            ? "Sin sello de tiempo."
            : stamp.status === QUEUED
              ? "En cola: la autoridad de sellado aún no lo ha emitido. Se sella en cuanto haya conexión."
              : `Sellado el ${when(stamp.gen_time)} · política ${stamp.policy ?? "—"}.`}
        </Link>
        <Link name="Diario" state={journal ? "ok" : "missing"}>
          {journal ? (
            <>
              Diario anclado en la campaña · informe <code className="hash">{journal.sha256}</code>
            </>
          ) : (
            "El diario todavía no está anclado en esta campaña."
          )}
        </Link>
      </ol>
    </section>
  );
}
