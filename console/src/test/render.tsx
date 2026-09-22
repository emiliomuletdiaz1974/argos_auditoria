// A view rendered against a fake v1 API: answers by path, and remembers what was sent to it.
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { SWRConfig } from "swr";

import { ApiProvider } from "../api/context";
import type { ApiFetch } from "../api/client";

export interface Sent {
  path: string;
  method: string;
  body: unknown;
}

export function renderWithApi(ui: ReactElement, routes: Record<string, unknown>) {
  const sent: Sent[] = [];
  const requested: string[] = [];
  const answers = { ...routes };
  const api: ApiFetch = async (path, init = {}) => {
    const method = (init.method ?? "GET").toUpperCase();
    requested.push(`${method} ${path}`);
    if (method !== "GET") {
      sent.push({ path, method, body: init.body ? JSON.parse(String(init.body)) : null });
      const reply = answers[`${method} ${path}`] ?? {};
      return new Response(JSON.stringify(reply), { status: 200 });
    }
    const found = Object.entries(answers).find(([route]) => route === path || path.startsWith(`${route}?`));
    if (!found) {
      return new Response(JSON.stringify({ title: "not found" }), { status: 404 });
    }
    // An answer may carry its own status: { __status: 409, detail: "…" } is a problem, not a body.
    const { __status: status = 200, ...body } = found[1] as { __status?: number };
    return new Response(JSON.stringify(body), { status });
  };
  const view = render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <ApiProvider api={api}>{ui}</ApiProvider>
    </SWRConfig>,
  );
  return { ...view, sent, requested, answers };
}
