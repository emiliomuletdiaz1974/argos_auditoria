// ARG-088 · the operator reads the package before it leaves: the index and every file, in clear.
import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import { renderWithApi } from "../../test/render";
import { SupportView } from "./SupportView";

const ID = "1790244000-0a1b2c3d";
const BASE = "/api/v1/support/diagnostics";
const INDEX_SHA = "e".repeat(64);

function ready() {
  return {
    id: ID,
    status: "ready",
    index_sha256: INDEX_SHA,
    index: {
      format: 1,
      generated_at: "2026-09-24T10:00:00Z",
      note: "Paquete de diagnóstico de ARGOS para el soporte. Lea cada fichero antes de enviarlo.",
      files: [],
    },
    files: [
      { name: "logs/api.log", size: 40, sha256: "1".repeat(64), scrubbed: 2, content: "# scrubbed: 2\nGET [DNI-1] 404\n" },
      { name: "versions.txt", size: 30, sha256: "2".repeat(64), scrubbed: 0, content: "installed 0.1.0\napi argos-api:dev\n" },
    ],
  };
}

describe("SupportView", () => {
  it("asks for a package and waits while it is collected", async () => {
    const { sent } = renderWithApi(<SupportView />, {
      [`POST ${BASE}`]: { __status: 202, id: ID, status: "collecting" },
      [`${BASE}/${ID}`]: { id: ID, status: "collecting" },
    });
    fireEvent.click(screen.getByRole("button", { name: /preparar un paquete/i }));
    expect(await screen.findByText(/recogiendo/i)).toBeTruthy();
    expect(sent).toEqual([{ path: BASE, method: "POST", body: null }]);
    expect(screen.queryByRole("button", { name: /cifrar/i })).toBeNull();
  });

  it("shows the note, the index and every file before anything can leave", async () => {
    renderWithApi(<SupportView />, {
      [`POST ${BASE}`]: { __status: 202, id: ID, status: "collecting" },
      [`${BASE}/${ID}`]: ready(),
    });
    fireEvent.click(screen.getByRole("button", { name: /preparar un paquete/i }));
    const index = await screen.findByRole("table", { name: /índice/i });
    expect(within(index).getByText("logs/api.log")).toBeTruthy();
    expect(within(index).getByText("versions.txt")).toBeTruthy();
    expect(within(index).getAllByRole("row")).toHaveLength(3);
    expect(screen.getByText(/lea cada fichero/i)).toBeTruthy();
    expect(screen.getByText(INDEX_SHA)).toBeTruthy();
    expect(screen.getByText(/GET \[DNI-1\] 404/)).toBeTruthy();
    expect(screen.getByText(/api argos-api:dev/)).toBeTruthy();
    expect(screen.getByRole("button", { name: /cifrar/i })).toBeDisabled();
  });

  it("encrypts only the index the operator confirmed", async () => {
    const { sent } = renderWithApi(<SupportView />, {
      [`POST ${BASE}`]: { __status: 202, id: ID, status: "collecting" },
      [`${BASE}/${ID}`]: ready(),
      [`POST ${BASE}/${ID}/package`]: {},
    });
    fireEvent.click(screen.getByRole("button", { name: /preparar un paquete/i }));
    fireEvent.click(await screen.findByRole("checkbox", { name: /he leído/i }));
    fireEvent.click(screen.getByRole("button", { name: /cifrar/i }));
    await waitFor(() =>
      expect(sent.at(-1)).toEqual({
        path: `${BASE}/${ID}/package`,
        method: "POST",
        body: { approved_index_sha256: INDEX_SHA },
      }),
    );
  });

  it("says why a package was refused", async () => {
    renderWithApi(<SupportView />, {
      [`POST ${BASE}`]: { __status: 202, id: ID, status: "collecting" },
      [`${BASE}/${ID}`]: ready(),
      [`POST ${BASE}/${ID}/package`]: { __status: 422, detail: "logs/api.log changed after the index was generated" },
    });
    fireEvent.click(screen.getByRole("button", { name: /preparar un paquete/i }));
    fireEvent.click(await screen.findByRole("checkbox", { name: /he leído/i }));
    fireEvent.click(screen.getByRole("button", { name: /cifrar/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/changed after the index/);
  });
});
