// ARG-073 · the session: PKCE against the Keycloak of the appliance, access token in memory only.
import { Session, type OidcConfig } from "./session";

const CONFIG: OidcConfig = {
  issuer: "https://keycloak.appliance.example/realms/argos",
  clientId: "argos-console",
  redirectUri: "https://argos.appliance.example/callback",
};
const TOKEN = "an-access-token-that-must-never-be-stored";

function answering(body: unknown, status = 200): typeof fetch {
  return vi.fn(async () => new Response(JSON.stringify(body), { status })) as unknown as typeof fetch;
}

function everythingStored(): string {
  const all: string[] = [];
  for (const storage of [window.localStorage, window.sessionStorage]) {
    for (let i = 0; i < storage.length; i += 1) {
      const key = storage.key(i) ?? "";
      all.push(key, storage.getItem(key) ?? "");
    }
  }
  return all.join("\n");
}

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
});

describe("Session", () => {
  it("sends the person to Keycloak with an S256 challenge and never the verifier", async () => {
    const navigate = vi.fn();
    await new Session(CONFIG, { fetch: answering({}), navigate }).login();

    const url = new URL(navigate.mock.calls[0]?.[0] as string);
    expect(url.origin + url.pathname).toBe(`${CONFIG.issuer}/protocol/openid-connect/auth`);
    expect(url.searchParams.get("code_challenge_method")).toBe("S256");
    expect(url.searchParams.get("client_id")).toBe("argos-console");
    expect(url.searchParams.get("response_type")).toBe("code");
    expect(url.searchParams.get("code_challenge")).toBeTruthy();
    const pending = JSON.parse(window.sessionStorage.getItem("argos.pkce") ?? "{}");
    expect(url.toString()).not.toContain(pending.verifier);
  });

  it("keeps the access token in memory and nowhere else", async () => {
    const navigate = vi.fn();
    const login = new Session(CONFIG, { fetch: answering({}), navigate });
    await login.login();
    const state = new URL(navigate.mock.calls[0]?.[0] as string).searchParams.get("state");

    const exchange = answering({ access_token: TOKEN, expires_in: 300 });
    const session = new Session(CONFIG, { fetch: exchange, navigate });
    await session.completeLogin(`${CONFIG.redirectUri}?code=the-code&state=${state}`);

    expect(session.accessToken()).toBe(TOKEN);
    expect(everythingStored()).not.toContain(TOKEN);
    expect(window.sessionStorage.getItem("argos.pkce")).toBeNull();

    const [path, init] = (exchange as unknown as ReturnType<typeof vi.fn>).mock.calls[0] as [
      string,
      RequestInit,
    ];
    expect(path).toBe("/api/v1/auth/session");
    const sent = JSON.parse(String(init.body));
    expect(sent).toMatchObject({ code: "the-code", redirect_uri: CONFIG.redirectUri });
    expect(sent.code_verifier).toBeTruthy();
  });

  it("refuses a callback whose state it did not send", async () => {
    const session = new Session(CONFIG, { fetch: answering({}), navigate: vi.fn() });
    await session.login();
    await expect(
      session.completeLogin(`${CONFIG.redirectUri}?code=the-code&state=someone-elses`),
    ).rejects.toThrow(/state/);
    expect(session.accessToken()).toBeNull();
  });

  it("renews from the cookie and says when it could not", async () => {
    const renewed = new Session(CONFIG, {
      fetch: answering({ access_token: TOKEN, expires_in: 300 }),
      navigate: vi.fn(),
    });
    await expect(renewed.refresh()).resolves.toBe(true);
    expect(renewed.accessToken()).toBe(TOKEN);
    expect(everythingStored()).not.toContain(TOKEN);

    const expired = new Session(CONFIG, { fetch: answering({}, 401), navigate: vi.fn() });
    await expect(expired.refresh()).resolves.toBe(false);
    expect(expired.accessToken()).toBeNull();
  });
});
