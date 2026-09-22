// ARG-075 · the campaigns: the list, and each one in its own screen.
import "./campaigns.css";

import { useResource } from "../../api/context";
import { CampaignDetail } from "./CampaignDetail";

export const CAMPAIGN_PREFIX = "/campaigns/";

interface CampaignRow {
  id: string;
  name: string;
  status: string;
  created_at: string;
}

function CampaignList() {
  const { data, error } = useResource<{ items: CampaignRow[] }>("/api/v1/campaigns");
  if (error) {
    return <p role="alert">No se pudieron leer las campañas: {error.detail}</p>;
  }
  if (!data) {
    return <p className="muted">Cargando las campañas…</p>;
  }
  return (
    <section className="panel" aria-label="Campañas">
      <h1>Campañas</h1>
      {data.items.length === 0 ? <p className="muted">Todavía no hay campañas.</p> : null}
      <ul className="campaign-list">
        {data.items.map((campaign) => (
          <li key={campaign.id}>
            <a href={`${CAMPAIGN_PREFIX}${campaign.id}`}>{campaign.name}</a>{" "}
            <span className="chip">{campaign.status}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function CampaignsView({ path }: { path: string }) {
  if (path.startsWith(CAMPAIGN_PREFIX) && path.length > CAMPAIGN_PREFIX.length) {
    return <CampaignDetail campaignId={path.slice(CAMPAIGN_PREFIX.length)} />;
  }
  return <CampaignList />;
}
