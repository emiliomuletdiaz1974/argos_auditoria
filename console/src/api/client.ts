// ARG-073 · the one door the console uses to talk to the v1 API.
//
// Every call carries the access token the session holds in memory. A 401 means it expired: the
// session renews once from the refresh cookie and the call is retried once. A second 401 is handed
// back as it came, so an expired session never turns into a loop.
//
// A 401 that says `insufficient_user_authentication` (RFC 9470, F09-07) is not an expired token:
// the action asks for a second factor, so the person is sent to sign in again with it.
import type { Session } from "../auth/session";

export type ApiFetch = (path: string, init?: RequestInit) => Promise<Response>;

export function createApiFetch(session: Session, network: typeof fetch = fetch): ApiFetch {
  const send = (path: string, init: RequestInit): Promise<Response> => {
    const headers = new Headers(init.headers);
    const token = session.accessToken();
    if (token) {
      headers.set("Authorization", `Bearer ${token}`);
    }
    return network(path, { ...init, headers, credentials: "same-origin" });
  };

  return async (path, init = {}) => {
    const first = await send(path, init);
    if (first.status !== 401) {
      return first;
    }
    if ((first.headers.get("WWW-Authenticate") ?? "").includes("insufficient_user_authentication")) {
      await session.requireSecondFactor();
      return first;
    }
    if (!(await session.refresh())) {
      return first;
    }
    return send(path, init);
  };
}
