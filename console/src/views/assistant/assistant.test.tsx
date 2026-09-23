// ARG-078 · the assistant is trusted for three reasons: its citations unfold, the tools it used are
// in sight, and when it does not know it says so. And it never gives a verdict.
import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import { renderWithApi } from "../../test/render";
import { AssistantView } from "./AssistantView";

const ASK = "POST /api/v1/assistant/ask";
const NOTICE = "Texto asistido por el modelo local de ARGOS: no es un veredicto ni sustituye a la revisión.";

const ANSWER = {
  answer: "El art. 32.1.a pide cifrado [1]; no hay hallazgos críticos [2].",
  sources: [
    { tool: "search_regulation", detail: "RGPD art. 32.1.a" },
    { tool: "finding_status", detail: "0 críticos" },
  ],
  calls: ["search_regulation", "finding_status"],
  fragments: [{ reference: "RGPD art. 32.1.a", text: "la seudonimización y el cifrado de los datos personales" }],
  complete: true,
  refused: false,
  assisted: true,
  notice: NOTICE,
};

function ask(question: string) {
  fireEvent.change(screen.getByLabelText(/tu pregunta/i), { target: { value: question } });
  fireEvent.click(screen.getByRole("button", { name: /preguntar/i }));
}

describe("AssistantView", () => {
  it("sends the question and unfolds each citation to its fragment and its origin", async () => {
    const { sent } = renderWithApi(<AssistantView />, { [ASK]: ANSWER });
    ask("¿qué pide el RGPD de cifrado?");
    await waitFor(() =>
      expect(sent).toEqual([
        { path: "/api/v1/assistant/ask", method: "POST", body: { question: "¿qué pide el RGPD de cifrado?" } },
      ]),
    );
    const answer = await screen.findByRole("article", { name: /respuesta/i });
    const first = within(answer).getByRole("button", { name: "Cita 1" });
    expect(first).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(first);
    expect(first).toHaveAttribute("aria-expanded", "true");
    const cited = within(answer).getByRole("region", { name: /cita 1/i });
    expect(cited).toHaveTextContent("RGPD art. 32.1.a");
    expect(cited).toHaveTextContent(/cifrado de los datos personales/);
    expect(cited).toHaveTextContent(/normativa/i);

    fireEvent.click(within(answer).getByRole("button", { name: "Cita 2" }));
    expect(within(answer).getByRole("region", { name: /cita 2/i })).toHaveTextContent(/0 críticos.*hallazgos/i);
  });

  it("a citation without its detail unfolds to no fragment rather than to the first one", async () => {
    // Security review F09-02, SEC-033: an empty detail matched every fragment.
    renderWithApi(<AssistantView />, {
      [ASK]: { ...ANSWER, answer: "Hay que cifrar [1].", sources: [{ tool: "search_regulation", detail: "" }] },
    });
    ask("¿qué pide el RGPD de cifrado?");
    const answer = await screen.findByRole("article", { name: /respuesta/i });
    fireEvent.click(within(answer).getByRole("button", { name: "Cita 1" }));
    const cited = within(answer).getByRole("region", { name: /cita 1/i });
    expect(cited).not.toHaveTextContent(/cifrado de los datos personales/);
  });

  it("shows under each answer the tools it consulted", async () => {
    renderWithApi(<AssistantView />, { [ASK]: ANSWER });
    ask("¿qué pide el RGPD de cifrado?");
    const answer = await screen.findByRole("article", { name: /respuesta/i });
    const tools = within(answer).getByRole("list", { name: /herramientas consultadas/i });
    expect(within(tools).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "Búsqueda en la normativa",
      "Estado de los hallazgos",
    ]);
  });

  it("presents a refusal as a refusal, with the nearest fragments to judge", async () => {
    renderWithApi(<AssistantView />, {
      [ASK]: {
        ...ANSWER,
        answer: "Lo recuperado no cubre esa pregunta.",
        sources: [],
        calls: ["search_regulation"],
        complete: false,
        refused: true,
      },
    });
    ask("¿cuánto se conservan las radiografías?");
    const answer = await screen.findByRole("article", { name: /sin respuesta/i });
    expect(answer).toHaveTextContent(/no hay base suficiente para responder/i);
    const nearest = within(answer).getByRole("list", { name: /fragmentos más cercanos/i });
    expect(within(nearest).getByText(/cifrado de los datos personales/)).toBeTruthy();
  });

  it("an answer cut by the budget says it is incomplete", async () => {
    renderWithApi(<AssistantView />, {
      [ASK]: { ...ANSWER, answer: "No he podido responder con las 5 consultas.", sources: [], complete: false, refused: false, fragments: [] },
    });
    ask("una pregunta enorme");
    const answer = await screen.findByRole("article", { name: /incompleta/i });
    expect(answer).toHaveTextContent(/5 consultas/);
  });

  it("keeps the notice in the footer at all times: the assistant does not give verdicts", () => {
    renderWithApi(<AssistantView />, {});
    expect(screen.getByRole("contentinfo")).toHaveTextContent(/no son veredictos de conformidad/i);
  });

  it("without the local model it says so clearly instead of failing", async () => {
    renderWithApi(<AssistantView />, {
      [ASK]: { __status: 503, detail: "the local model is not available" },
    });
    ask("¿qué pide el RGPD de cifrado?");
    expect(await screen.findByRole("status")).toHaveTextContent(/el modelo local no está disponible/i);
    expect(screen.getByLabelText(/tu pregunta/i)).toBeEnabled();
  });

  it("a quota spent is told apart from a model that is not there", async () => {
    renderWithApi(<AssistantView />, {
      [ASK]: { __status: 429, detail: "quota exhausted" },
    });
    ask("¿qué pide el RGPD de cifrado?");
    expect(await screen.findByRole("status")).toHaveTextContent(/cupo/i);
  });
});
