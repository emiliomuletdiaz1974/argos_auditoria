// ARG-075 · the campaign manager's cycle in one screen: plan, approve, follow and close.
import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import { renderWithApi } from "../../test/render";
import { CampaignDetail } from "./CampaignDetail";
import { GateTray } from "./GateTray";
import { LiveProgress } from "./LiveProgress";
import { PlanPreview } from "./PlanPreview";

const ID = "0192b000-0000-7000-8000-000000000001";
const PLAN = {
  campaign_id: ID,
  units: [
    {
      unit_id: "u1",
      challenge_id: "sec-encryption-in-transit",
      obligation: "OBL-RGPD-32-3",
      node_key: "k-1",
      severity: "high",
      probe: { kind: "sql", target: "public.patients", statement: "SHOW ssl", params: {} },
    },
    {
      unit_id: "u2",
      challenge_id: "sec-encryption-in-transit",
      obligation: "OBL-RGPD-32-3",
      node_key: "k-2",
      severity: "high",
      probe: { kind: "sql", target: "public.visits", statement: "SHOW ssl", params: {} },
    },
    {
      unit_id: "u3",
      challenge_id: "sec-encryption-at-rest",
      obligation: "OBL-RGPD-32-1",
      node_key: "k-3",
      severity: "critical",
      probe: { kind: "configuration", target: "pg_settings", statement: null, params: {} },
    },
  ],
  unverifiable: [
    {
      challenge_id: "ai-risk-register",
      node_key: "k-9",
      reason: "the challenge is reserved in the catalog but not written yet",
      system_id: "s-1",
      connector: null,
    },
  ],
  probes_run: 0,
};

describe("PlanPreview", () => {
  it("shows literally what will be asked, grouped by obligation, before anything runs", async () => {
    renderWithApi(<PlanPreview campaignId={ID} />, { [`/api/v1/campaigns/${ID}/plan`]: PLAN });
    const group = await screen.findByRole("group", { name: /OBL-RGPD-32-3/ });
    expect(within(group).getByText(/2 comprobaciones/)).toBeTruthy();
    expect(within(group).getAllByText("SHOW ssl")).toHaveLength(2);
    expect(within(group).getByText("public.visits")).toBeTruthy();
    expect(screen.getByRole("group", { name: /OBL-RGPD-32-1/ })).toBeTruthy();
    expect(screen.getByText(/ninguna sonda se ha ejecutado todavía/i)).toBeTruthy();
  });

  it("puts what cannot be verified in its own section, with the reason", async () => {
    renderWithApi(<PlanPreview campaignId={ID} />, { [`/api/v1/campaigns/${ID}/plan`]: PLAN });
    const section = await screen.findByRole("region", { name: /no verificable/i });
    expect(within(section).getByText("ai-risk-register")).toBeTruthy();
    expect(within(section).getByText(/reserved in the catalog/)).toBeTruthy();
  });

  it("explains that there is no plan until the campaign is prepared", async () => {
    renderWithApi(<PlanPreview campaignId={ID} />, {
      [`/api/v1/campaigns/${ID}/plan`]: { __status: 409, detail: "no plan until the campaign is prepared" },
    });
    expect(await screen.findByRole("status")).toHaveTextContent(/todavía no hay plan/i);
  });
});

describe("GateTray", () => {
  const GATES = {
    items: [
      { gate: "start", payload: { units: 3 }, approvals: 1, needed: 1, approved_by: ["user:ana"], requested_at: "x" },
      { gate: "sampling", payload: { units: 3 }, approvals: 1, needed: 2, approved_by: ["user:ana"], requested_at: "y" },
    ],
  };

  it("says who has approved and that a different person is still missing", async () => {
    renderWithApi(<GateTray campaignId={ID} />, { [`/api/v1/campaigns/${ID}/gates`]: GATES });
    const sampling = await screen.findByRole("listitem", { name: /muestreo/i });
    expect(within(sampling).getByText(/1 de 2/)).toBeTruthy();
    expect(within(sampling).getByText(/falta 1 aprobación de otra persona/i)).toBeTruthy();
    expect(within(sampling).getByText(/user:ana/)).toBeTruthy();
    const start = screen.getByRole("listitem", { name: /arranque/i });
    expect(within(start).getByText(/aprobada/i)).toBeTruthy();
    expect(within(start).queryByRole("button")).toBeNull();
  });

  it("approves a pending gate", async () => {
    const { sent } = renderWithApi(<GateTray campaignId={ID} />, {
      [`/api/v1/campaigns/${ID}/gates`]: GATES,
    });
    const sampling = await screen.findByRole("listitem", { name: /muestreo/i });
    fireEvent.click(within(sampling).getByRole("button", { name: /aprobar/i }));
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]?.path).toBe(`/api/v1/campaigns/${ID}/gates/sampling/approve`);
  });
});

describe("LiveProgress", () => {
  it("shows the progress and the systems paused by their circuit, with the reason", async () => {
    renderWithApi(<LiveProgress campaignId={ID} />, {
      [`/api/v1/campaigns/${ID}/progress`]: {
        status: "running",
        done: 12,
        total: 40,
        findings: 3,
        paused: [{ system_id: "s-2", reason: "latencia p50 de 900 ms" }],
      },
    });
    const bar = await screen.findByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "12");
    expect(bar).toHaveAttribute("aria-valuemax", "40");
    expect(screen.getByText(/3 hallazgos/)).toBeTruthy();
    const paused = screen.getByRole("list", { name: /en pausa/i });
    expect(within(paused).getByText(/s-2/)).toBeTruthy();
    expect(within(paused).getByText(/latencia p50 de 900 ms/)).toBeTruthy();
  });
});

describe("CampaignDetail", () => {
  it("offers the dossier once the campaign is sealed", async () => {
    const { requested } = renderWithApi(<CampaignDetail campaignId={ID} />, {
      [`/api/v1/campaigns/${ID}`]: { id: ID, name: "Campaña de otoño", status: "sealed", seal: "abc", seal_verified: true },
      [`/api/v1/campaigns/${ID}/gates`]: { items: [] },
    });
    fireEvent.click(await screen.findByRole("button", { name: /descargar el expediente/i }));
    await waitFor(() => expect(requested).toContain(`GET /api/v1/evidence/${ID}/dossier.pdf`));
  });

  it("does not offer a dossier that does not exist yet", async () => {
    renderWithApi(<CampaignDetail campaignId={ID} />, {
      [`/api/v1/campaigns/${ID}`]: { id: ID, name: "Campaña en marcha", status: "running", seal: null },
      [`/api/v1/campaigns/${ID}/gates`]: { items: [] },
      [`/api/v1/campaigns/${ID}/progress`]: { status: "running", done: 0, total: 1, findings: 0, paused: [] },
    });
    await screen.findByRole("heading", { name: /Campaña en marcha/ });
    expect(screen.queryByRole("button", { name: /descargar el expediente/i })).toBeNull();
  });
});
