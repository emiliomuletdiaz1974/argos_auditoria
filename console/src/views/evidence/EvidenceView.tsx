// ARG-077 · the evidence: the sealed campaigns, and each one with its chain, its downloads, its
// artifacts and its credential. `#journal-<seq>` opens the journal entry a finding points to.
import "./evidence.css";

import { useResource } from "../../api/context";
import { ArtifactBrowser } from "./ArtifactBrowser";
import { EvidenceChain } from "./EvidenceChain";
import { EvidenceDownloads } from "./EvidenceDownloads";
import { IssueCredential } from "./IssueCredential";
import { JournalEntry } from "./JournalEntry";

export const EVIDENCE_PREFIX = "/evidence/";
const JOURNAL_ANCHOR = /^#journal-(\d+)$/;
const SEALED = "sealed";

interface CampaignRow {
  id: string;
  name: string;
  status: string;
}

function SealedCampaigns() {
  const { data, error } = useResource<{ items: CampaignRow[] }>("/api/v1/campaigns");
  if (error) {
    return <p role="alert">No se pudieron leer las campañas: {error.detail}</p>;
  }
  if (!data) {
    return <p className="muted">Cargando las campañas…</p>;
  }
  const sealed = data.items.filter((campaign) => campaign.status === SEALED);
  return (
    <section className="panel" aria-label="Evidencia">
      <h1>Evidencia</h1>
      {sealed.length === 0 ? <p className="muted">Ninguna campaña sellada todavía: la evidencia se cierra al sellar.</p> : null}
      <ul className="campaign-list">
        {sealed.map((campaign) => (
          <li key={campaign.id}>
            <a href={`${EVIDENCE_PREFIX}${campaign.id}`}>{campaign.name}</a>
          </li>
        ))}
      </ul>
    </section>
  );
}

function CampaignEvidence({ campaignId, anchor }: { campaignId: string; anchor: string }) {
  const cited = JOURNAL_ANCHOR.exec(anchor);
  return (
    <div className="evidence-detail">
      <h1>Evidencia de la campaña</h1>
      <p className="muted">
        <code>{campaignId}</code>
      </p>
      {cited ? <JournalEntry campaignId={campaignId} seq={Number(cited[1])} /> : null}
      <EvidenceChain campaignId={campaignId} />
      <EvidenceDownloads campaignId={campaignId} />
      <ArtifactBrowser campaignId={campaignId} />
      <IssueCredential campaignId={campaignId} />
    </div>
  );
}

export function EvidenceView({ path, anchor = "" }: { path: string; anchor?: string }) {
  if (path.startsWith(EVIDENCE_PREFIX) && path.length > EVIDENCE_PREFIX.length) {
    return <CampaignEvidence campaignId={path.slice(EVIDENCE_PREFIX.length)} anchor={anchor} />;
  }
  return <SealedCampaigns />;
}
