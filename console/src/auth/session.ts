// ARG-073 · the console session (ADR-0013).
//
// The person signs in at the Keycloak of the appliance with PKCE. The code comes back to the
// console, which hands it with its verifier to the API: the API exchanges it, keeps the refresh
// token in an HttpOnly cookie that only `/api/v1/auth` (refresh and logout) sees, and answers with
// the access token alone. The cookie lasts as long as the browser, and «Salir» revokes it. That token lives in this object's memory and nowhere else: not in localStorage, not
// in sessionStorage. What survives the redirect to Keycloak is the verifier and the state, never a
// token, and they are removed as soon as the sign-in completes.
import { challengeOf, newVerifier } from "./pkce";

export interface OidcConfig {
  issuer: string;
  clientId: string;
  redirectUri: string;
}

export interface SessionDeps {
  fetch: typeof fetch;
  navigate: (url: string) => void;
}

const PENDING = "argos.pkce";
// F09-07: where the person was when an action asked for the second factor (a path, never a token).
const SECOND_FACTOR_RETURN = "argos.second-factor";
const SESSION_PATH = "/api/v1/auth/session";
const REFRESH_PATH = "/api/v1/auth/refresh";
const LOGOUT_PATH = "/api/v1/auth/logout";

interface TokenAnswer {
  access_token?: string;
}

export class Session {
  #token: string | null = null;

  constructor(
    private readonly config: OidcConfig,
    private readonly deps: SessionDeps,
  ) {}

  accessToken(): string | null {
    return this.#token;
  }

  async login(secondFactor = false): Promise<void> {
    const verifier = newVerifier();
    const state = newVerifier();
    window.sessionStorage.setItem(PENDING, JSON.stringify({ verifier, state }));
    const params = new URLSearchParams({
      client_id: this.config.clientId,
      redirect_uri: this.config.redirectUri,
      response_type: "code",
      scope: "openid",
      state,
      code_challenge: await challengeOf(verifier),
      code_challenge_method: "S256",
    });
    if (secondFactor) {
      // Sign in again, with the second factor (RFC 9470): not the session the realm remembers.
      params.set("prompt", "login");
      params.set("acr_values", "otp");
    }
    const url = new URL(`${this.config.issuer}/protocol/openid-connect/auth`);
    url.search = params.toString();
    this.deps.navigate(url.toString());
  }

  /** The API asked for the second factor: sign in again with it and come back to this page. */
  async requireSecondFactor(): Promise<void> {
    window.sessionStorage.setItem(
      SECOND_FACTOR_RETURN,
      window.location.pathname + window.location.search + window.location.hash,
    );
    await this.login(true);
  }

  /** Where to go back after signing in with the second factor, once; null if nothing asked. */
  takeSecondFactorReturn(): string | null {
    const back = window.sessionStorage.getItem(SECOND_FACTOR_RETURN);
    window.sessionStorage.removeItem(SECOND_FACTOR_RETURN);
    return back && back.startsWith("/") && !back.startsWith("//") ? back : null;
  }

  async completeLogin(callbackUrl: string): Promise<void> {
    const params = new URL(callbackUrl).searchParams;
    const pending = JSON.parse(window.sessionStorage.getItem(PENDING) ?? "{}") as {
      verifier?: string;
      state?: string;
    };
    window.sessionStorage.removeItem(PENDING);
    if (!pending.state || params.get("state") !== pending.state) {
      throw new Error("the sign-in came back with a state this console did not send");
    }
    const code = params.get("code");
    if (!code || !pending.verifier) {
      throw new Error("the sign-in came back without a code");
    }
    const answer = await this.deps.fetch(SESSION_PATH, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        code,
        code_verifier: pending.verifier,
        redirect_uri: this.config.redirectUri,
      }),
    });
    if (!answer.ok) {
      throw new Error(`the sign-in was refused (${answer.status})`);
    }
    this.#token = ((await answer.json()) as TokenAnswer).access_token ?? null;
  }

  /** Renew from the refresh cookie. True when there is a new access token in memory. */
  async refresh(): Promise<boolean> {
    const answer = await this.deps.fetch(REFRESH_PATH, { method: "POST", credentials: "same-origin" });
    if (!answer.ok) {
      this.#token = null;
      return false;
    }
    this.#token = ((await answer.json()) as TokenAnswer).access_token ?? null;
    return this.#token !== null;
  }

  /** Close the session: the API revokes the refresh token and deletes its cookie. */
  async logout(): Promise<void> {
    this.#token = null;
    await this.deps.fetch(LOGOUT_PATH, { method: "POST", credentials: "same-origin" });
  }
}
