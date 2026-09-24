// ARG-090 · the airlock screen: what the medium brought and what happened to each file, and what
// may leave, from the closed list only.
import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import { renderWithApi } from "../../test/render";
import { AirgapView } from "./AirgapView";

const IMPORTS = "/api/v1/airgap/imports";
const EXPORTS = "/api/v1/airgap/exports";
const CAMPAIGN = "0192b000-0000-7000-8000-000000000001";

describe("AirgapView", () => {
  it("shows each file of the medium with its result, its reason and its hash", async () => {
    renderWithApi(<AirgapView />, {
      [`POST ${IMPORTS}`]: {
        results: [
          { file: "argos-update-0.2.0.tar", kind: "update", result: "imported", reason: "update 0.2.0 verified and queued for the updater", sha256: "a".repeat(64), size: 10 },
          { file: "notes.txt", kind: null, result: "rejected", reason: "not a kind the airlock imports", sha256: null, size: null },
        ],
      },
    });
    fireEvent.click(screen.getByRole("button", { name: /leer el soporte/i }));
    const table = await screen.findByRole("table", { name: /lo que trajo el soporte/i });
    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(3);
    expect(within(rows[1]!).getByText(/importado/i)).toBeTruthy();
    expect(within(rows[1]!).getByText("a".repeat(64))).toBeTruthy();
    expect(within(rows[2]!).getByText(/rechazado/i)).toBeTruthy();
    expect(within(rows[2]!).getByText(/not a kind the airlock imports/)).toBeTruthy();
  });

  it("offers only the kinds of the closed list", () => {
    renderWithApi(<AirgapView />, {});
    const kinds = within(screen.getByRole("combobox", { name: /qué sale/i }))
      .getAllByRole("option")
      .map((option) => (option as HTMLOptionElement).value);
    expect(kinds.sort()).toEqual(["credential", "diagnostics", "dossier", "tsq"]);
  });

  it("exports a dossier of a campaign and lists what was written", async () => {
    const { sent } = renderWithApi(<AirgapView />, {
      [`POST ${EXPORTS}`]: {
        __status: 201,
        id: "20260924T100000Z-dossier-0a1b2c3d",
        kind: "dossier",
        files: [{ name: `dossier-${CAMPAIGN}.json`, size: 100, sha256: "b".repeat(64) }],
      },
    });
    fireEvent.change(screen.getByRole("combobox", { name: /qué sale/i }), { target: { value: "dossier" } });
    fireEvent.change(screen.getByLabelText(/campaña/i), { target: { value: CAMPAIGN } });
    fireEvent.click(screen.getByRole("button", { name: /escribir en el soporte/i }));
    expect(await screen.findByText("b".repeat(64))).toBeTruthy();
    await waitFor(() =>
      expect(sent.at(-1)).toEqual({ path: EXPORTS, method: "POST", body: { kind: "dossier", campaign_id: CAMPAIGN } }),
    );
  });

  it("says why an export was refused", async () => {
    renderWithApi(<AirgapView />, {
      [`POST ${EXPORTS}`]: { __status: 422, detail: "no object is waiting for its time stamp" },
    });
    fireEvent.click(screen.getByRole("button", { name: /escribir en el soporte/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/waiting for its time stamp/);
  });
});
