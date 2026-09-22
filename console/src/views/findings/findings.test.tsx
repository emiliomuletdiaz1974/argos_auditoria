// ARG-076 · "what do I do first?": the worst first, the whole why, and no way to close by hand.
import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import { renderWithApi } from "../../test/render";
import { AcceptRiskModal } from "./AcceptRiskModal";
import { FindingDetail } from "./FindingDetail";
import { FindingsBoard } from "./FindingsBoard";

const ID = "0192c000-0000-7000-8000-000000000001";
const CAMPAIGN = "0192b000-0000-7000-8000-000000000001";
const VERDICT = "0192d000-0000-7000-8000-000000000001";

function row(id: string, severity: string, occurrences: number, status = "open") {
  return {
    id,
    challenge_id: `ch-${id}`,
    obligation: "OBL-RGPD-32-1",
    system_id: "s-1",
    node_key: `k-${id}`,
    severity,
    severity_rank: { low: 1, medium: 2, high: 3, critical: 4 }[severity],
    status,
    occurrences,
    campaign_id: CAMPAIGN,
    risk_expiry: null,
    updated_at: "2026-09-20T10:00:00+00:00",
    order_key: "x",
  };
}

function detail(overrides: Record<string, unknown> = {}) {
  return {
    id: ID,
    fingerprint: "f".repeat(64),
    campaign_id: CAMPAIGN,
    challenge_id: "sec-encryption-in-transit",
    obligation: {
      id: "OBL-RGPD-32-1",
      norm: "RGPD",
      article: "32.1.a",
      title: "Cifrado de los datos personales",
      summary: "…",
    },
    system_id: "s-1",
    node_key: "k-1",
    severity: "high",
    status: "open",
    occurrences: 1,
    campaigns_seen: [CAMPAIGN],
    detail: {},
    risk_note: null,
    risk_expiry: null,
    created_at: "2026-09-20T10:00:00+00:00",
    updated_at: "2026-09-20T10:00:00+00:00",
    verdict: {
      id: VERDICT,
      result: "non_compliant",
      verdict: { detail: { field: "rows.0.ssl", operator: "==", observed: "off", expected: "on" } },
      verdict_hash: "a".repeat(64),
      challenge_version: "1.0",
      sampling: { confidence: "0.95", failures: 4, population: 1200, projected_upper: 30, sample: 300, upper_rate: "0.025" },
      probe_journal: { seq: 4242, action: "probe.issued", at: "2026-09-20T09:59:00Z" },
      created_at: "2026-09-20T10:00:00+00:00",
    },
    allowed_transitions: ["in_remediation", "risk_accepted"],
    history: [
      { seq: 4243, at: "2026-09-20T10:00:00+00:00", actor: "system:campaign", action: "finding.open", from: null, to: "open", occurrences: 1 },
    ],
    ...overrides,
  };
}

const PATH = `/api/v1/findings/${ID}`;

describe("FindingsBoard", () => {
  beforeEach(() => window.history.replaceState(null, "", "/findings"));

  it("keeps the order of the API: worst first, then the most recurrent", async () => {
    renderWithApi(<FindingsBoard />, {
      "/api/v1/findings": { items: [row("a", "critical", 3), row("b", "high", 5), row("c", "low", 9)], next_cursor: null },
    });
    const links = await screen.findAllByRole("link");
    expect(links.map((link) => link.textContent)).toEqual(["ch-a", "ch-b", "ch-c"]);
    expect(screen.getByText(/3 veces/)).toBeTruthy();
  });

  it("filters through the API and keeps the filters in the address", async () => {
    const { requested } = renderWithApi(<FindingsBoard />, {
      "/api/v1/findings": { items: [row("a", "critical", 1)], next_cursor: null },
    });
    await screen.findByText("ch-a");
    fireEvent.change(screen.getByLabelText("Severidad"), { target: { value: "critical" } });
    fireEvent.change(screen.getByLabelText("Estado"), { target: { value: "reopened" } });
    await waitFor(() =>
      expect(requested).toContain("GET /api/v1/findings?severity=critical&status=reopened"),
    );
    expect(window.location.search).toBe("?severity=critical&status=reopened");
  });

  it("starts from the filters it finds in the address", async () => {
    window.history.replaceState(null, "", "/findings?status=pending_verification");
    const { requested } = renderWithApi(<FindingsBoard />, {
      "/api/v1/findings": { items: [], next_cursor: null },
    });
    expect(await screen.findByText(/ningún hallazgo/i)).toBeTruthy();
    expect(requested).toContain("GET /api/v1/findings?status=pending_verification");
    expect(screen.getByLabelText("Estado")).toHaveValue("pending_verification");
  });
});

describe("FindingDetail", () => {
  it("tells the whole why: the values seen, the sample, the journal entry and the article", async () => {
    renderWithApi(<FindingDetail findingId={ID} />, { [PATH]: detail() });
    const why = await screen.findByRole("region", { name: /por qué/i });
    expect(within(why).getByText("off")).toBeTruthy();
    expect(within(why).getByText("on")).toBeTruthy();
    expect(within(why).getByText(/300 de 1200/)).toBeTruthy();
    expect(within(why).getByText(/95 %/)).toBeTruthy();
    const entry = within(why).getByRole("link", { name: /asiento 4242/i });
    expect(entry).toHaveAttribute("href", `/evidence/${CAMPAIGN}#journal-4242`);
    expect(within(why).getByText(/RGPD · art\. 32\.1\.a/)).toBeTruthy();
  });

  it("offers exactly the transitions the API allows, and never closing by hand", async () => {
    renderWithApi(<FindingDetail findingId={ID} />, { [PATH]: detail() });
    const actions = await screen.findByRole("group", { name: /acciones/i });
    const labels = within(actions).getAllByRole("button").map((button) => button.textContent);
    expect(labels).toEqual(["Pasar a remediación", "Aceptar el riesgo"]);
    expect(screen.queryByRole("button", { name: /cerrar/i })).toBeNull();
  });

  it("moves the finding through the API and reads it again", async () => {
    const { sent, requested } = renderWithApi(<FindingDetail findingId={ID} />, { [PATH]: detail() });
    fireEvent.click(await screen.findByRole("button", { name: "Pasar a remediación" }));
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]).toEqual({ path: `${PATH}/transition`, method: "POST", body: { to: "in_remediation" } });
    await waitFor(() => expect(requested.filter((line) => line === `GET ${PATH}`)).toHaveLength(2));
  });

  it("a finding awaiting verification offers only the re-run, never a close", async () => {
    const { sent } = renderWithApi(<FindingDetail findingId={ID} />, {
      [PATH]: detail({ status: "pending_verification", allowed_transitions: [] }),
    });
    const rerun = await screen.findByRole("button", { name: /volver a ejecutar el reto/i });
    expect(screen.getByText(/solo la reejecución/i)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /cerrar/i })).toBeNull();
    fireEvent.click(rerun);
    await waitFor(() => expect(sent).toEqual([{ path: `${PATH}/verify`, method: "POST", body: {} }]));
  });

  it("a reopened finding shows its history", async () => {
    renderWithApi(<FindingDetail findingId={ID} />, {
      [PATH]: detail({
        status: "reopened",
        occurrences: 2,
        history: [
          { seq: 1, at: "2026-09-01T10:00:00Z", actor: "system:campaign", action: "finding.open", from: null, to: "open", occurrences: 1 },
          { seq: 2, at: "2026-09-02T10:00:00Z", actor: "user:dpo", action: "finding.transition", from: "open", to: "risk_accepted", occurrences: null },
          { seq: 3, at: "2026-09-30T10:00:00Z", actor: "system:risk-expiry", action: "finding.transition", from: "risk_accepted", to: "reopened", occurrences: null },
        ],
      }),
    });
    const history = await screen.findByRole("list", { name: /historia/i });
    const steps = within(history).getAllByRole("listitem");
    expect(steps).toHaveLength(3);
    expect(steps[1]).toHaveTextContent(/Riesgo aceptado.*user:dpo/);
    expect(steps[2]).toHaveTextContent(/Reabierto.*system:risk-expiry/);
  });
});

describe("AcceptRiskModal", () => {
  it("demands a justification and an expiry, and warns it goes to the journal and the dossier", async () => {
    const onAccept = vi.fn();
    renderWithApi(<AcceptRiskModal open onAccept={onAccept} onCancel={() => undefined} />, {});
    const dialog = screen.getByRole("dialog", { name: /aceptar el riesgo/i });
    expect(within(dialog).getByText(/queda en el diario y en el expediente/i)).toBeTruthy();
    const confirm = within(dialog).getByRole("button", { name: "Aceptar el riesgo" });
    expect(confirm).toBeDisabled();

    fireEvent.change(within(dialog).getByLabelText(/justificación/i), { target: { value: "corto" } });
    fireEvent.change(within(dialog).getByLabelText(/caduca/i), { target: { value: "2027-03-01" } });
    expect(confirm).toBeDisabled();
    expect(within(dialog).getByText(/al menos 20 caracteres/i)).toBeTruthy();

    const reason = "El sistema se retira en marzo y el cifrado llega con el sustituto.";
    fireEvent.change(within(dialog).getByLabelText(/justificación/i), { target: { value: reason } });
    expect(confirm).toBeEnabled();
    fireEvent.click(confirm);
    expect(onAccept).toHaveBeenCalledWith({ note: reason, risk_expiry: "2027-03-01" });
  });

  it("accepting from the detail sends the note and the expiry", async () => {
    const { sent } = renderWithApi(<FindingDetail findingId={ID} />, { [PATH]: detail() });
    fireEvent.click(await screen.findByRole("button", { name: "Aceptar el riesgo" }));
    const dialog = screen.getByRole("dialog");
    const reason = "El sistema se retira en marzo y el cifrado llega con el sustituto.";
    fireEvent.change(within(dialog).getByLabelText(/justificación/i), { target: { value: reason } });
    fireEvent.change(within(dialog).getByLabelText(/caduca/i), { target: { value: "2027-03-01" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Aceptar el riesgo" }));
    await waitFor(() =>
      expect(sent).toEqual([
        {
          path: `${PATH}/transition`,
          method: "POST",
          body: { to: "risk_accepted", note: reason, risk_expiry: "2027-03-01" },
        },
      ]),
    );
  });
});
