// ARG-075 · one campaign, section by section as its state allows: plan, gates, progress, dossier.
import { useState } from "react";

import { download, useApi, useResource, type ApiError } from "../../api/context";
import { GateTray } from "./GateTray";
import { LiveProgress } from "./LiveProgress";
import { PlanPreview } from "./PlanPreview";

interface Campaign {
  id: string;
  name: string;
  status: string;
  seal: string | null;
  seal_verified?: boolean;
}

const STATUS_LABELS: Record<string, string> = {
  planned: "Planificada",
  pinned: "Preparada",
  running: "En marcha",
  sealed: "Sellada",
  failed: "Fallida",
};

export function CampaignDetail({ campaignId }: { campaignId: string }) {
  const api = useApi();
  const { data, error } = useResource<Campaign>(`/api/v1/campaigns/${campaignId}`);
  const [problem, setProblem] = useState<string | null>(null);

  if (error) {
    return <p role="alert">{error.status === 404 ? "Esa campaña no existe." : error.detail}</p>;
  }
  if (!data) {
    return <p className="muted">Cargando la campaña…</p>;
  }
  const sealed = data.status === "sealed";
  const getDossier = async () => {
    setProblem(null);
    try {
      await download(api, `/api/v1/evidence/${campaignId}/dossier.pdf`, `expediente-${campaignId}.pdf`);
    } catch (failure) {
      setProblem((failure as ApiError).detail);
    }
  };

  return (
    <div className="campaign-detail">
      <h1>{data.name}</h1>
      <p className="muted">{STATUS_LABELS[data.status] ?? data.status}</p>
      {sealed ? (
        <section className="panel" aria-label="Cierre">
          <h2>Cierre</h2>
          <p className="muted">
            La campaña está sellada{data.seal_verified ? " y su sello verifica" : ""}. El expediente reúne la evidencia.
          </p>
          <button type="button" className="btn-primary" onClick={() => void getDossier()}>
            Descargar el expediente
          </button>
          {problem ? <p role="alert">{problem}</p> : null}
        </section>
      ) : null}
      <GateTray campaignId={campaignId} />
      {data.status === "running" ? <LiveProgress campaignId={campaignId} /> : null}
      {data.status !== "planned" ? <PlanPreview campaignId={campaignId} /> : null}
    </div>
  );
}
