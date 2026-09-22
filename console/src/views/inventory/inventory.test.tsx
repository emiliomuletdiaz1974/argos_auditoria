// ARG-074 · the inventory view: what there is, how much is known of it, and what waits for a person.
import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import { renderWithApi } from "../../test/render";
import { InventoryMap } from "./InventoryMap";
import { NodeExplorer } from "./NodeExplorer";
import { ReviewQueue } from "./ReviewQueue";

const COVERAGE = {
  systems: [
    {
      system_id: "s-1",
      system_name: "HIS clínico",
      coverage_pct: 87.5,
      columns_total: 40,
      special_columns: 6,
      missing_assets: 2,
      pending_review: 3,
      last_scan_at: "2026-09-20 10:00:00+00",
    },
  ],
  pending_review: 3,
  special_columns: 6,
  missing_assets: 2,
};
const NODE = {
  node: { key: "col:his:patients:dni", label: "Column", name: "dni", qualified_name: "public.patients.dni", system_id: "s-1" },
  props: { source_connector: "argos_sql.postgres:PostgresConnector", first_seen: "2026-09-01T08:00:00+00:00", last_seen: "2026-09-20T10:00:00+00:00" },
  neighbours: [
    { edge: "HAS_COLUMN", direction: "in", key: "tab:his:patients", label: "Table", name: "patients", qualified_name: "public.patients", system_id: "s-1" },
    { edge: "CLASSIFIED_AS", direction: "out", key: "cat:official_identifier", label: "Category", name: "official_identifier", qualified_name: null, system_id: null },
  ],
  has_more: false,
  deltas: [{ kind: "appeared", detail: {}, at: "2026-09-01T08:00:00+00:00", run_id: "r-1" }],
};
const QUEUE = {
  items: [
    {
      node_key: "col:his:notes:obs_txt",
      qualified_name: "public.notes.obs_txt",
      proposed_category: "special_category.health",
      confidence: 0.7,
      reason: "texto libre clínico",
      status: "pending",
    },
  ],
  next: null,
};

describe("InventoryMap", () => {
  it("makes the coverage the big number and warns of special data in amber, never gold", async () => {
    renderWithApi(<InventoryMap />, { "/api/v1/inventory/coverage": COVERAGE });
    const card = await screen.findByRole("article", { name: /HIS clínico/ });
    expect(within(card).getByText("87,5 %")).toHaveClass("coverage-figure");
    const special = within(card).getByText(/6 columnas de categoría especial/);
    expect(special).toHaveClass("chip-high");
    expect(special.className).not.toMatch(/verdict|gold/);
    expect(within(card).getByText(/2 nodos desaparecidos/)).toBeTruthy();
    expect(within(card).getByText(/3 pendientes de revisión/)).toBeTruthy();
  });
});

describe("NodeExplorer", () => {
  it("shows where each node comes from, its neighbourhood and its timeline", async () => {
    renderWithApi(<NodeExplorer nodeKey="col:his:patients:dni" />, {
      "/api/v1/inventory/nodes/col%3Ahis%3Apatients%3Adni": NODE,
    });
    expect(await screen.findByRole("heading", { name: /public\.patients\.dni/ })).toBeTruthy();
    expect(screen.getByText(/argos_sql\.postgres:PostgresConnector/)).toBeTruthy();
    expect(screen.getByText(/visto por última vez/i)).toBeTruthy();
    const neighbours = screen.getByRole("list", { name: /vecindario/i });
    expect(within(neighbours).getAllByRole("listitem")).toHaveLength(2);
    expect(within(neighbours).getByRole("link", { name: /public\.patients$/ })).toHaveAttribute(
      "href",
      "/inventory/nodes/tab%3Ahis%3Apatients",
    );
    const timeline = screen.getByRole("list", { name: /línea temporal/i });
    expect(within(timeline).getByText(/apareció/i)).toBeTruthy();
  });

  it("says so when the node does not exist", async () => {
    renderWithApi(<NodeExplorer nodeKey="nothing" />, {});
    expect(await screen.findByRole("alert")).toHaveTextContent(/no existe/i);
  });
});

describe("ReviewQueue", () => {
  it("confirms the proposal of the model in one click", async () => {
    const { sent } = renderWithApi(<ReviewQueue />, { "/api/v1/inventory/review-queue": QUEUE });
    fireEvent.click(await screen.findByRole("button", { name: /confirmar/i }));
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]).toMatchObject({
      method: "POST",
      path: "/api/v1/inventory/review-queue/col%3Ahis%3Anotes%3Aobs_txt",
      body: { decision: "accept" },
    });
  });

  it("corrects it to another category, which also teaches the calibration", async () => {
    const { sent } = renderWithApi(<ReviewQueue />, { "/api/v1/inventory/review-queue": QUEUE });
    const row = await screen.findByRole("article", { name: /public\.notes\.obs_txt/ });
    fireEvent.change(within(row).getByRole("combobox", { name: /corregir a/i }), {
      target: { value: "special_category.other" },
    });
    fireEvent.click(within(row).getByRole("button", { name: /corregir/i }));
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]?.body).toEqual({ decision: "correct", category: "special_category.other" });
  });

  it("every action is a real button, reachable with the keyboard", async () => {
    renderWithApi(<ReviewQueue />, { "/api/v1/inventory/review-queue": QUEUE });
    const buttons = await screen.findAllByRole("button");
    expect(buttons.length).toBeGreaterThanOrEqual(3);
    for (const button of buttons) {
      expect(button.tagName).toBe("BUTTON");
      expect(button.getAttribute("tabindex")).not.toBe("-1");
    }
  });

  it("says when nothing is waiting", async () => {
    renderWithApi(<ReviewQueue />, { "/api/v1/inventory/review-queue": { items: [], next: null } });
    expect(await screen.findByText(/no hay columnas pendientes/i)).toBeTruthy();
  });
});
