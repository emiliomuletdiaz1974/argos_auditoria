// ARG-073 · the shell of the console: a session, a navigation and room for the views to come.
import { useEffect, useMemo, useState } from "react";

import { Session } from "./auth/session";
import { CALLBACK_PATH, oidcConfig } from "./config";

const SECTIONS = [
  { path: "/inventory", label: "Inventario" },
  { path: "/campaigns", label: "Campañas" },
  { path: "/findings", label: "Hallazgos" },
  { path: "/evidence", label: "Evidencia" },
  { path: "/assistant", label: "Asistente" },
];

type Status = "starting" | "signed-in" | "signed-out" | "failed";

export function App() {
  const session = useMemo(
    () => new Session(oidcConfig(), { fetch, navigate: (url) => window.location.assign(url) }),
    [],
  );
  const [status, setStatus] = useState<Status>("starting");
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    const start = async () => {
      if (window.location.pathname === CALLBACK_PATH) {
        await session.completeLogin(window.location.href);
        window.history.replaceState(null, "", "/");
        return true;
      }
      return session.refresh();
    };
    start()
      .then((signedIn) => setStatus(signedIn ? "signed-in" : "signed-out"))
      .catch((error: unknown) => {
        setProblem(error instanceof Error ? error.message : String(error));
        setStatus("failed");
      });
  }, [session]);

  if (status === "starting") {
    return <p className="shell-main muted">Comprobando la sesión…</p>;
  }
  if (status !== "signed-in") {
    return (
      <main className="shell-main">
        <div className="panel">
          <h1>ARGOS</h1>
          {problem ? <p className="muted">{problem}</p> : null}
          <button type="button" className="btn-primary" onClick={() => void session.login()}>
            Entrar
          </button>
        </div>
      </main>
    );
  }
  return (
    <div className="shell">
      <nav className="shell-nav" aria-label="Secciones">
        {SECTIONS.map((section) => (
          <a
            key={section.path}
            href={section.path}
            aria-current={window.location.pathname === section.path ? "page" : undefined}
          >
            {section.label}
          </a>
        ))}
      </nav>
      <main className="shell-main">
        <div className="panel">
          <h1>Consola de ARGOS</h1>
          <p className="muted">Las vistas llegan con las tareas F08-11 a F08-15.</p>
        </div>
      </main>
    </div>
  );
}
