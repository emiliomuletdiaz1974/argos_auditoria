// ARG-077 · the view ARGOS is shown to third parties with: every link as it really is, and gold only
// for what is accredited.
import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import { renderWithApi } from "../../test/render";
import { ArtifactBrowser } from "./ArtifactBrowser";
import { EvidenceChain } from "./EvidenceChain";
import { EvidenceDownloads } from "./EvidenceDownloads";
import { IssueCredential } from "./IssueCredential";
import { JournalEntry } from "./JournalEntry";

const ID = "0192b000-0000-7000-8000-000000000001";
const SHA = "d".repeat(64);
const CHAIN = `/api/v1/evidence/${ID}/chain`;

function chain(overrides: Record<string, unknown> = {}) {
  return {
    artifacts: [
      { verdict_id: "v-1", key: "k1", version_id: "1", sha256: "1".repeat(64) },
      { verdict_id: "v-2", key: "k2", version_id: "1", sha256: "2".repeat(64) },
    ],
    merkle: { root: "a".repeat(64), leaf_count: 2, leaf_order: "verdict_id", tree_key: "t" },
    signature: { key: "s", version_id: "1", sha256: "b".repeat(64), key_id: "argos-evidence", non_production: true },
    time_stamp: { status: "queued", gen_time: null, policy: null, token_key: null },
    journal_report: { key: "j", version_id: "1", sha256: "c".repeat(64) },
    ...overrides,
  };
}

function subject(nonProduction: boolean) {
  return {
    id: `urn:argos:campaign:${ID}`,
    type: "ComplianceCampaign",
    campaignId: ID,
    dossierSha256: SHA,
    merkleRoot: "a".repeat(64),
    sealedAt: "2026-09-20T10:00:00Z",
    libraryVersion: "1.0.0",
    ontologyVersion: "1.0.0",
    units: 2,
    results: { compliant: 1, non_compliant: 1 },
    findingsBySeverity: { high: 1 },
    nonProduction,
  };
}

const PREVIEW = `/api/v1/credentials/preview?campaign_id=${ID}`;

function preview(nonProduction = true) {
  return {
    dossier_sha256: SHA,
    credentialSubject: subject(nonProduction),
    withheld: ["approvals", "campaign.name", "evidence_chain.artifacts", "findings", "results_by_obligation", "texts"],
  };
}

function gold(container: HTMLElement) {
  return container.querySelectorAll(".chip-verdict, .credential-seal");
}

describe("EvidenceChain", () => {
  it("says each link as it is: a queued stamp is queued, a development signature says so", async () => {
    const { container } = renderWithApi(<EvidenceChain campaignId={ID} />, { [CHAIN]: chain() });
    const links = await screen.findByRole("list", { name: /eslabones/i });
    expect(within(links).getByText(/2 artefactos/)).toBeTruthy();
    expect(within(links).getByText(/raíz de 2 hojas/i)).toBeTruthy();
    const signature = within(links).getByRole("listitem", { name: /firma/i });
    expect(signature).toHaveTextContent(/clave de desarrollo/i);
    expect(signature).toHaveTextContent(/no vale fuera de las pruebas/i);
    expect(within(links).getByRole("listitem", { name: /sello/i })).toHaveTextContent(/en cola/i);
    expect(within(links).getByRole("listitem", { name: /diario/i })).toHaveTextContent(/anclado/i);
    expect(gold(container)).toHaveLength(0);
  });

  it("says what is missing instead of hiding it", async () => {
    renderWithApi(<EvidenceChain campaignId={ID} />, {
      [CHAIN]: chain({ merkle: null, signature: null, time_stamp: null, journal_report: null }),
    });
    const links = await screen.findByRole("list", { name: /eslabones/i });
    expect(within(links).getByRole("listitem", { name: /raíz/i })).toHaveTextContent(/todavía no/i);
    expect(within(links).getByRole("listitem", { name: /firma/i })).toHaveTextContent(/sin firmar/i);
    expect(within(links).getByRole("listitem", { name: /sello/i })).toHaveTextContent(/sin sello/i);
  });

  it("shows a stamped signature with its time and policy", async () => {
    renderWithApi(<EvidenceChain campaignId={ID} />, {
      [CHAIN]: chain({ time_stamp: { status: "stamped", gen_time: "2026-09-20T10:00:00Z", policy: "1.2.3.4", token_key: "t" } }),
    });
    const stamp = await screen.findByRole("listitem", { name: /sello/i });
    expect(stamp).toHaveTextContent(/sellado el/i);
    expect(stamp).toHaveTextContent("1.2.3.4");
  });
});

describe("ArtifactBrowser", () => {
  const LIST = `/api/v1/evidence/${ID}/artifacts`;

  it("pages through the artifacts and downloads each one with its inclusion proof", async () => {
    const { requested } = renderWithApi(<ArtifactBrowser campaignId={ID} />, {
      [LIST]: { items: [{ verdict_id: "v-1", sha256: "1".repeat(64), created_at: "2026-09-20T10:00:00Z" }], next: "c2" },
      [`${LIST}?cursor=c2`]: { items: [{ verdict_id: "v-2", sha256: "2".repeat(64), created_at: "2026-09-20T09:00:00Z" }], next: null },
      "/api/v1/evidence/artifacts/v-1": { verdict_id: "v-1", proof: { index: 0 } },
    });
    await screen.findByText("v-1");
    fireEvent.click(screen.getByRole("button", { name: /más artefactos/i }));
    await screen.findByText("v-2");
    expect(screen.queryByRole("button", { name: /más artefactos/i })).toBeNull();

    const first = screen.getByRole("row", { name: /v-1/ });
    fireEvent.click(within(first).getByRole("button", { name: /con su prueba de inclusión/i }));
    await waitFor(() => expect(requested).toContain("GET /api/v1/evidence/artifacts/v-1"));
  });
});

describe("EvidenceDownloads", () => {
  it("offers the dossier in JSON and PDF and the bundle for a third party", async () => {
    const { requested } = renderWithApi(<EvidenceDownloads campaignId={ID} />, {
      [`/api/v1/evidence/${ID}/dossier.json`]: {},
      [`/api/v1/evidence/${ID}/dossier.pdf`]: {},
      [`/api/v1/evidence/${ID}/bundle`]: {},
    });
    fireEvent.click(screen.getByRole("button", { name: /expediente en json/i }));
    fireEvent.click(screen.getByRole("button", { name: /expediente en pdf/i }));
    fireEvent.click(screen.getByRole("button", { name: /paquete de verificación/i }));
    await waitFor(() =>
      expect(requested).toEqual([
        `GET /api/v1/evidence/${ID}/dossier.json`,
        `GET /api/v1/evidence/${ID}/dossier.pdf`,
        `GET /api/v1/evidence/${ID}/bundle`,
      ]),
    );
    expect(screen.getByText(/cada descarga queda en el diario/i)).toBeTruthy();
  });
});

describe("IssueCredential", () => {
  it("previews exactly what travels and what stays, and issues only on explicit confirmation", async () => {
    const { sent, container } = renderWithApi(<IssueCredential campaignId={ID} />, {
      [PREVIEW]: preview(),
      "POST /api/v1/credentials": {
        credential_id: "cred-1",
        revoked: false,
        credential: { credentialSubject: subject(true) },
      },
    });
    const travels = await screen.findByRole("table", { name: /lo que viaja/i });
    expect(within(travels).getByText("dossierSha256")).toBeTruthy();
    expect(within(travels).getByText(SHA)).toBeTruthy();
    const stays = screen.getByRole("list", { name: /lo que no viaja/i });
    expect(within(stays).getByText(/quién aprobó/i)).toBeTruthy();
    expect(within(stays).getByText(/los hallazgos y dónde/i)).toBeTruthy();

    const issue = screen.getByRole("button", { name: /emitir la credencial/i });
    expect(issue).toBeDisabled();
    fireEvent.click(screen.getByLabelText(/he revisado/i));
    fireEvent.click(issue);
    await waitFor(() =>
      expect(sent).toEqual([{ path: "/api/v1/credentials", method: "POST", body: { campaign_id: ID, dossier_sha256: SHA } }]),
    );
    expect(await screen.findByText(/credencial de desarrollo/i)).toBeTruthy();
    expect(gold(container)).toHaveLength(0);
  });

  it("an accredited credential is the one thing that glows gold", async () => {
    const { container } = renderWithApi(<IssueCredential campaignId={ID} />, {
      [PREVIEW]: preview(false),
      "POST /api/v1/credentials": {
        credential_id: "cred-1",
        revoked: false,
        credential: { credentialSubject: subject(false) },
      },
    });
    await screen.findByRole("table", { name: /lo que viaja/i });
    expect(gold(container)).toHaveLength(0);
    fireEvent.click(screen.getByLabelText(/he revisado/i));
    fireEvent.click(screen.getByRole("button", { name: /emitir la credencial/i }));
    await screen.findByText(/credencial emitida/i);
    expect(gold(container)).toHaveLength(1);
  });

  it("when the dossier changed since the preview, it says so and reads the preview again", async () => {
    const { requested } = renderWithApi(<IssueCredential campaignId={ID} />, {
      [PREVIEW]: preview(),
      "POST /api/v1/credentials": { __status: 409, detail: "the dossier changed since the preview" },
    });
    await screen.findByRole("table", { name: /lo que viaja/i });
    fireEvent.click(screen.getByLabelText(/he revisado/i));
    fireEvent.click(screen.getByRole("button", { name: /emitir la credencial/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/el expediente ha cambiado/i);
    await waitFor(() => expect(requested.filter((line) => line === `GET ${PREVIEW}`)).toHaveLength(2));
    expect(screen.getByLabelText(/he revisado/i)).not.toBeChecked();
  });
});

describe("JournalEntry", () => {
  it("shows the entry a finding points to: action, moment and the literal question", async () => {
    renderWithApi(<JournalEntry campaignId={ID} seq={4242} />, {
      [`/api/v1/evidence/${ID}/journal/4242`]: {
        seq: 4242,
        at: "2026-09-20T09:59:00Z",
        actor: "system:probe",
        action: "probe.issued",
        payload: { target: "public.patients", statement: "SHOW ssl" },
        entry_hash: "e".repeat(64),
      },
    });
    const entry = await screen.findByRole("region", { name: /asiento 4242/i });
    expect(entry).toHaveAttribute("id", "journal-4242");
    expect(within(entry).getByText("probe.issued")).toBeTruthy();
    expect(within(entry).getByText(/SHOW ssl/)).toBeTruthy();
    expect(within(entry).getByText("e".repeat(64))).toBeTruthy();
  });

  it("an entry no verdict of the campaign cites is not shown", async () => {
    renderWithApi(<JournalEntry campaignId={ID} seq={2} />, {});
    expect(await screen.findByRole("alert")).toHaveTextContent(/ningún veredicto de esta campaña cita el asiento 2/i);
  });
});
