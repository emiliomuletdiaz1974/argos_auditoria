// ARG-078 · the console assistant. Three rules make it trustworthy: every [n] unfolds to its source
// and, for the regulation, the fragment it came from; the tools it consulted are listed under each
// answer; and a refusal is shown as a refusal, with the nearest fragments for the person to judge.
// The footer says it every time: what the assistant writes is not a verdict of compliance.
// The conversation lives only in this screen: nothing of it is stored in the browser.
import { useState, type FormEvent } from "react";

import { send, useApi, type ApiError } from "../../api/context";
import "./assistant.css";

interface Source {
  tool: string;
  detail: string;
}

interface Fragment {
  reference: string;
  text: string;
}

interface Answer {
  answer: string;
  sources: Source[];
  calls: string[];
  fragments: Fragment[];
  complete: boolean;
  refused: boolean;
  notice: string;
}

interface Turn {
  question: string;
  answer: Answer;
}

const TOOL_LABELS: Record<string, string> = {
  search_regulation: "Búsqueda en la normativa",
  finding_status: "Estado de los hallazgos",
  inventory_coverage: "Cobertura del inventario",
  query_graph: "Consulta al grafo del inventario",
};

const REFUSALS: Record<number, string> = {
  429: "Se ha agotado el cupo del modelo local por ahora. Vuelve a preguntar dentro de un rato.",
  502: "El modelo respondió algo que no se puede enseñar como respuesta (citaba lo que no consultó). Reformula la pregunta.",
  503: "El modelo local no está disponible en este equipo. El resto de la consola funciona; el asistente vuelve cuando el modelo esté en marcha.",
};

const CITATION = /\[(\d+)\]/g;

function fragmentOf(source: Source, fragments: Fragment[]): Fragment | undefined {
  return fragments.find((fragment) => source.detail.includes(fragment.reference) || fragment.reference.includes(source.detail));
}

function Citation({ number, source, fragments }: { number: number; source: Source | undefined; fragments: Fragment[] }) {
  const [open, setOpen] = useState(false);
  if (!source) {
    return <span>[{number}]</span>;
  }
  const fragment = fragmentOf(source, fragments);
  return (
    <>
      <button
        type="button"
        className="citation"
        aria-label={`Cita ${number}`}
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        [{number}]
      </button>
      {open ? (
        <span role="region" aria-label={`Cita ${number}`} className="citation-body">
          <strong>{source.detail}</strong> · {TOOL_LABELS[source.tool] ?? source.tool}
          {fragment ? <q>{fragment.text}</q> : null}
        </span>
      ) : null}
    </>
  );
}

function AnswerText({ answer }: { answer: Answer }) {
  const parts: Array<string | number> = [];
  let last = 0;
  for (const match of answer.answer.matchAll(CITATION)) {
    parts.push(answer.answer.slice(last, match.index));
    parts.push(Number(match[1]));
    last = (match.index ?? 0) + match[0].length;
  }
  parts.push(answer.answer.slice(last));
  return (
    <p>
      {parts.map((part, index) =>
        typeof part === "number" ? (
          <Citation key={index} number={part} source={answer.sources[part - 1]} fragments={answer.fragments} />
        ) : (
          <span key={index}>{part}</span>
        ),
      )}
    </p>
  );
}

function Tools({ calls }: { calls: string[] }) {
  if (calls.length === 0) {
    return null;
  }
  return (
    <>
      <h3 className="muted">De dónde sale</h3>
      <ul aria-label="Herramientas consultadas" className="tools">
        {calls.map((call, index) => (
          <li key={index}>{TOOL_LABELS[call] ?? call}</li>
        ))}
      </ul>
    </>
  );
}

function Reply({ answer }: { answer: Answer }) {
  if (answer.refused) {
    return (
      <article aria-label="Sin respuesta" className="reply reply-refused">
        <p>
          <strong>No hay base suficiente para responder.</strong> {answer.answer}
        </p>
        {answer.fragments.length > 0 ? (
          <>
            <h3 className="muted">Los fragmentos más cercanos, por si quieres juzgarlo tú</h3>
            <ul aria-label="Fragmentos más cercanos">
              {answer.fragments.map((fragment) => (
                <li key={fragment.reference}>
                  <strong>{fragment.reference}</strong> · <q>{fragment.text}</q>
                </li>
              ))}
            </ul>
          </>
        ) : null}
        <Tools calls={answer.calls} />
      </article>
    );
  }
  return (
    <article aria-label={answer.complete ? "Respuesta" : "Respuesta incompleta"} className="reply">
      {answer.complete ? null : <p className="muted">Respuesta incompleta.</p>}
      <AnswerText answer={answer} />
      <Tools calls={answer.calls} />
    </article>
  );
}

export function AssistantView() {
  const api = useApi();
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [waiting, setWaiting] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const asked = question.trim();
    if (!asked) {
      return;
    }
    setProblem(null);
    setWaiting(true);
    try {
      const answer = await send<Answer>(api, "/api/v1/assistant/ask", { question: asked });
      setTurns([...turns, { question: asked, answer }]);
      setQuestion("");
    } catch (failure) {
      const refused = failure as ApiError;
      setProblem(REFUSALS[refused.status] ?? refused.detail);
    } finally {
      setWaiting(false);
    }
  };

  return (
    <section className="panel assistant" aria-label="Asistente">
      <h1>Asistente</h1>
      <div className="conversation">
        {turns.map((turn, index) => (
          <div key={index} className="turn">
            <p className="question">{turn.question}</p>
            <Reply answer={turn.answer} />
          </div>
        ))}
      </div>
      {problem ? (
        <p role="status" className="assistant-down">
          {problem}
        </p>
      ) : null}
      <form onSubmit={(event) => void submit(event)} className="ask">
        <label className="field">
          Tu pregunta
          <textarea value={question} rows={3} maxLength={2000} onChange={(event) => setQuestion(event.target.value)} />
        </label>
        <div className="actions">
          <button type="submit" className="btn-primary" disabled={waiting || question.trim().length < 3}>
            {waiting ? "Pensando…" : "Preguntar"}
          </button>
        </div>
      </form>
      <footer className="muted assistant-notice">
        Las respuestas del asistente no son veredictos de conformidad: son texto asistido por el modelo local, con sus
        fuentes a la vista. Los veredictos los da el evaluador determinista.
      </footer>
    </section>
  );
}
