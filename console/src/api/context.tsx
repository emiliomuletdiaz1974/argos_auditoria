// The v1 API as the views see it: one `ApiFetch`, and SWR on top to read.
import { createContext, useContext, type ReactNode } from "react";
import useSWR, { type SWRResponse } from "swr";

import type { ApiFetch } from "./client";

const ApiContext = createContext<ApiFetch | null>(null);

export function ApiProvider({ api, children }: { api: ApiFetch; children: ReactNode }) {
  return <ApiContext.Provider value={api}>{children}</ApiContext.Provider>;
}

export function useApi(): ApiFetch {
  const api = useContext(ApiContext);
  if (!api) {
    throw new Error("a view was rendered outside the ApiProvider");
  }
  return api;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {
    super(detail);
  }
}

async function readJson<T>(api: ApiFetch, path: string): Promise<T> {
  const answer = await api(path);
  if (!answer.ok) {
    const problem = (await answer.json().catch(() => ({}))) as { detail?: string; title?: string };
    throw new ApiError(answer.status, problem.detail ?? problem.title ?? `error ${answer.status}`);
  }
  return (await answer.json()) as T;
}

/** Read a resource of the v1; `null` path means «not yet». */
export function useResource<T>(path: string | null): SWRResponse<T, ApiError> {
  const api = useApi();
  return useSWR<T, ApiError>(path, (key: string) => readJson<T>(api, key));
}

/** Send a mutation and return the parsed answer, or throw the problem the API explained. */
export async function send<T>(api: ApiFetch, path: string, body: unknown): Promise<T> {
  const answer = await api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!answer.ok) {
    const problem = (await answer.json().catch(() => ({}))) as { detail?: string };
    throw new ApiError(answer.status, problem.detail ?? `error ${answer.status}`);
  }
  return (await answer.json()) as T;
}
