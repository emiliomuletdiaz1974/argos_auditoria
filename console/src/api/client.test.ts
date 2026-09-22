// ARG-073 · every call carries the token in memory; a 401 renews once and retries once.
import { Session } from "../auth/session";
import { createApiFetch } from "./client";

const CONFIG = {
  issuer: "https://keycloak.appliance.example/realms/argos",
  clientId: "argos-console",
  redirectUri: "https://argos.appliance.example/callback",
};

function scripted(responses: Array<[number, unknown]>): ReturnType<typeof vi.fn> {
  const queue = [...responses];
  return vi.fn(async () => {
    const [status, body] = queue.shift() ?? [500, {}];
    return new Response(JSON.stringify(body), { status });
  });
}

describe("createApiFetch", () => {
  it("sends the token it holds in memory", async () => {
    const network = scripted([[200, { access_token: "first" }], [200, { items: [] }]]);
    const session = new Session(CONFIG, { fetch: network as unknown as typeof fetch, navigate: vi.fn() });
    await session.refresh();
    const api = createApiFetch(session, network as unknown as typeof fetch);

    const answer = await api("/api/v1/campaigns");
    expect(answer.status).toBe(200);
    const [, init] = network.mock.calls[1] as [string, RequestInit];
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer first");
  });

  it("renews once after a 401 and retries once with the new token", async () => {
    const network = scripted([
      [401, { title: "unauthenticated" }],
      [200, { access_token: "renewed" }],
      [200, { items: [] }],
    ]);
    const session = new Session(CONFIG, { fetch: network as unknown as typeof fetch, navigate: vi.fn() });
    const api = createApiFetch(session, network as unknown as typeof fetch);

    expect((await api("/api/v1/findings")).status).toBe(200);
    const paths = network.mock.calls.map((call) => call[0]);
    expect(paths).toEqual(["/api/v1/findings", "/api/v1/auth/refresh", "/api/v1/findings"]);
    const [, retry] = network.mock.calls[2] as [string, RequestInit];
    expect(new Headers(retry.headers).get("Authorization")).toBe("Bearer renewed");
  });

  it("does not loop: a second 401 is handed back as it is", async () => {
    const network = scripted([
      [401, {}],
      [200, { access_token: "renewed" }],
      [401, {}],
    ]);
    const session = new Session(CONFIG, { fetch: network as unknown as typeof fetch, navigate: vi.fn() });
    const api = createApiFetch(session, network as unknown as typeof fetch);

    expect((await api("/api/v1/findings")).status).toBe(401);
    expect(network).toHaveBeenCalledTimes(3);
  });

  it("does not retry when the renewal itself fails", async () => {
    const network = scripted([
      [401, {}],
      [401, {}],
    ]);
    const session = new Session(CONFIG, { fetch: network as unknown as typeof fetch, navigate: vi.fn() });
    const api = createApiFetch(session, network as unknown as typeof fetch);

    expect((await api("/api/v1/findings")).status).toBe(401);
    expect(network).toHaveBeenCalledTimes(2);
  });
});
