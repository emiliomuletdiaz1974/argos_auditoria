// The v1 API as the views see it: one `ApiFetch`, and SWR on top to read.
import { createContext, useContext, type ReactNode } from "react";
import useSWR, { type SWRConfiguration, type SWRResponse } from "swr";

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

/** Read a resource of the v1; `null` path means «not yet». `options` go to SWR (polling, say). */
export function useResource<T>(path: string | null, options?: SWRConfiguration<T, ApiError>): SWRResponse<T, ApiError> {
  const api = useApi();
  return useSWR<T, ApiError>(path, (key: string) => readJson<T>(api, key), options);
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

/**
 * Download a file of the v1 with the token in memory. A plain link cannot carry the token, so the
 * file is fetched and handed to the browser as a local object URL. With a `body`, the file is the
 * answer to a POST (the diagnostic package, built for the index the operator approved).
 */
export async function download(api: ApiFetch, path: string, filename: string, body?: unknown): Promise<void> {
  const answer = await api(
    path,
    body === undefined
      ? undefined
      : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) },
  );
  if (!answer.ok) {
    const problem = (await answer.json().catch(() => ({}))) as { detail?: string };
    throw new ApiError(answer.status, problem.detail ?? `error ${answer.status}`);
  }
  const url = URL.createObjectURL(await answer.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}
