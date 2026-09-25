// ARG-092/099 · the operation screen: the eight lights, the active alerts and the runbook of each.
import { fireEvent, screen, within } from "@testing-library/react";

import { renderWithApi } from "../../test/render";
import { Markdown } from "./Markdown";
import { OperationsView } from "./OperationsView";

const STATUS = "/api/v1/operations/status";
const RUNBOOK = "/api/v1/operations/runbooks/RB-02-almacen-evidencia";

const LIGHTS = [
  { key: "journal", title: "Diario", state: "green", value: 1 },
  { key: "worm", title: "Almacén WORM", state: "red", value: 0 },
  { key: "services", title: "Servicios", state: "green", value: 1 },
  { key: "tsa", title: "Cola de sellado", state: "green", value: 0 },
  { key: "backup", title: "Copias", state: "unknown", value: null },
  { key: "evidence_disk", title: "Disco de evidencia", state: "green", value: 0.2 },
  { key: "certificates", title: "Certificados", state: "green", value: 0 },
  { key: "version", title: "Versión", state: "green", value: 1, text: "0.1.0-alpha" },
];
const ALERT = {
  alertname: "WormWriteFailing",
  severity: "critical",
  summary: "The WORM store does not keep what it is given",
  runbook: "RB-02-almacen-evidencia",
  labels: {},
  starts_at: "2026-09-25T08:00:00+00:00",
};

describe("OperationsView", () => {
  it("shows the eight lights with their state in words, not only in colour", async () => {
    renderWithApi(<OperationsView />, { [STATUS]: { lights: LIGHTS, alerts: [], measured: true } });
    const lights = await screen.findByRole("list", { name: /semáforos/i });
    const items = within(lights).getAllByRole("listitem");
    expect(items).toHaveLength(8);
    expect(within(items[1]!).getByText(/fallo/i)).toBeTruthy();
    expect(within(items[4]!).getByText(/sin medir/i)).toBeTruthy();
    expect(within(items[7]!).getByText("0.1.0-alpha")).toBeTruthy();
  });

  it("lists the active alerts and opens the runbook of one", async () => {
    renderWithApi(<OperationsView />, {
      [STATUS]: { lights: LIGHTS, alerts: [ALERT], measured: true },
      [RUNBOOK]: { id: "RB-02-almacen-evidencia", markdown: "# RB-02 · El almacén\n\n## Síntoma\n\nNo guarda." },
    });
    const alerts = await screen.findByRole("table", { name: /alertas activas/i });
    expect(within(alerts).getByText("WormWriteFailing")).toBeTruthy();
    expect(within(alerts).getByText(/crítica/i)).toBeTruthy();
    fireEvent.click(within(alerts).getByRole("button", { name: /RB-02/ }));
    expect(await screen.findByRole("heading", { name: /Síntoma/ })).toBeTruthy();
  });

  it("says so when nothing is being measured", async () => {
    renderWithApi(<OperationsView />, { [STATUS]: { lights: [], alerts: [], measured: false } });
    expect(await screen.findByText(/no está conectada a prometheus/i)).toBeTruthy();
  });
});

describe("Markdown", () => {
  it("renders headings, lists, code and emphasis as elements, never as raw HTML", () => {
    const text = "# Título\n\n## Acción\n\n- Uno **fuerte**\n- Dos `make backup`\n\n1. Primero\n\n```bash\nmake backup\n```\n\n<script>alert(1)</script>";
    const { container } = renderWithApi(<Markdown text={text} />, {});
    expect(screen.getByRole("heading", { level: 1, name: "Título" })).toBeTruthy();
    expect(screen.getByRole("heading", { level: 2, name: "Acción" })).toBeTruthy();
    expect(container.querySelectorAll("ul li")).toHaveLength(2);
    expect(container.querySelector("strong")?.textContent).toBe("fuerte");
    expect(container.querySelector("pre code")?.textContent).toContain("make backup");
    expect(container.querySelector("script")).toBeNull();
    expect(screen.getByText("<script>alert(1)</script>")).toBeTruthy();
  });
});
