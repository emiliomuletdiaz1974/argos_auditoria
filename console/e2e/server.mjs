// The appliance as the console sees it, for the end-to-end script: one origin that serves the built
// console, the v1 API and the sign-in of the realm.
//
// The API here is a stand-in, not the real one —the real one needs PostgreSQL, Temporal, Keycloak
// and the WORM store—, but it keeps the two rules the script exists to prove:
//
//   1. nothing moves without the call the interface makes: the plan appears when the campaign is
//      prepared, the run starts when the gate is approved, and the finding only exists once a unit
//      failed;
//   2. a finding is never closed by hand. `transition` refuses `closed_compliant` and `reopened`
//      with 409, exactly as the API does, and only the re-run of `verify` closes one, and only if
//      the challenge passes again.
//
// What the script drives is the console. This file only answers it.
import { createReadStream, existsSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("../dist/", import.meta.url));
const PORT = Number(process.env.E2E_PORT ?? 4173);
const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".svg": "image/svg+xml",
  ".json": "application/json; charset=utf-8",
};
const CAMPAIGN = "0192b000-0000-7000-8000-000000000001";
const SYSTEM = "0192a000-0000-7000-8000-000000000001";
const FINDING = "0192c000-0000-7000-8000-000000000001";
const VERDICT = "0192d000-0000-7000-8000-000000000001";
const SHA = "d".repeat(64);
const CODE = "authorization-code-of-the-script";

// The whole state of the stand-in. The script moves it only through the console; the only thing a
// test may do by hand is `POST /api/v1/__reset`, which puts this world back at the beginning
// between scripts. It resets, it never advances.
const initial = () => ({
  signedIn: false,
  remediated: false,
  campaign: { id: CAMPAIGN, name: "Campaña de otoño", status: "pinned", seal: null },
  gate: { gate: "start", approvals: 0, needed: 1, approved_by: [] },
  progress: { status: "running", done: 0, total: 2, findings: 0, paused: [] },
  finding: {
    id: FINDING,
    challenge_id: "sec-encryption-in-transit",
    obligation: "OBL-RGPD-32-1",
    system_id: SYSTEM,
    node_key: "public.patients.ssl",
    severity: "high",
    severity_rank: 3,
    status: "open",
    occurrences: 1,
    campaign_id: CAMPAIGN,
    risk_expiry: null,
    updated_at: "2026-09-22T10:00:00+00:00",
    order_key: "3-000001",
  },
  credential: null,
});

let state = initial();

const TRANSITIONS = {
  open: ["in_remediation", "risk_accepted"],
  in_remediation: ["pending_verification", "risk_accepted"],
  pending_verification: [],
  reopened: ["in_remediation", "risk_accepted"],
  risk_accepted: ["in_remediation"],
  closed_compliant: [],
};

const plan = () => ({
  campaign_id: CAMPAIGN,
  units: [
    {
      unit_id: "u1",
      challenge_id: "sec-encryption-in-transit",
      obligation: "OBL-RGPD-32-1",
      node_key: "public.patients.ssl",
      severity: "high",
      probe: { kind: "sql", target: "public.patients", statement: "SHOW ssl", params: {} },
    },
    {
      unit_id: "u2",
      challenge_id: "sec-encryption-at-rest",
      obligation: "OBL-RGPD-32-1",
      node_key: "public.patients.disk",
      severity: "critical",
      probe: { kind: "configuration", target: "pg_settings", statement: null, params: {} },
    },
  ],
  unverifiable: [],
  probes_run: state.progress.done,
});

const findingDetail = () => ({
  ...state.finding,
  fingerprint: "f".repeat(64),
  obligation: {
    id: "OBL-RGPD-32-1",
    norm: "RGPD",
    article: "32.1.a",
    title: "Seguridad del tratamiento",
    summary: "Medidas técnicas apropiadas, entre ellas el cifrado.",
  },
  campaigns_seen: [CAMPAIGN],
  detail: {},
  risk_note: null,
  created_at: "2026-09-22T10:00:00+00:00",
  verdict: {
    id: VERDICT,
    result: "non_compliant",
    verdict: { detail: { field: "rows.0.ssl", operator: "==", observed: "off", expected: "on" } },
    verdict_hash: "a".repeat(64),
    challenge_version: "1.0",
    sampling: null,
    probe_journal: { seq: 4242, action: "probe.issued", at: "2026-09-22T09:59:00+00:00" },
    created_at: "2026-09-22T10:00:00+00:00",
  },
  allowed_transitions: TRANSITIONS[state.finding.status],
  history: state.finding.history ?? [
    {
      seq: 4243,
      at: "2026-09-22T10:00:00+00:00",
      actor: "system:campaign",
      action: "finding.open",
      from: null,
      to: "open",
      occurrences: 1,
    },
  ],
});

function note(to, actor) {
  const history = state.finding.history ?? findingDetail().history;
  state.finding.history = [
    ...history,
    {
      seq: history[history.length - 1].seq + 1,
      at: new Date().toISOString(),
      actor,
      action: "finding.transition",
      from: state.finding.status,
      to,
      occurrences: null,
    },
  ];
  state.finding.status = to;
}

function problem(response, status, detail) {
  response.writeHead(status, { "Content-Type": "application/problem+json" });
  response.end(JSON.stringify({ type: "about:blank", title: detail, status, detail }));
}

function json(response, body, status = 200, headers = {}) {
  response.writeHead(status, { "Content-Type": "application/json; charset=utf-8", ...headers });
  response.end(JSON.stringify(body));
}

async function body(request) {
  const chunks = [];
  for await (const chunk of request) {
    chunks.push(chunk);
  }
  return chunks.length ? JSON.parse(Buffer.concat(chunks).toString()) : {};
}

function api(request, response, url) {
  const path = url.pathname.slice("/api/v1".length);
  const method = request.method;

  if (path === "/__reset" && method === "POST") {
    state = initial();
    return json(response, { reset: true });
  }
  if (path === "/auth/session" && method === "POST") {
    state.signedIn = true;
    return json(response, { access_token: "access-token-of-the-script" });
  }
  if (path === "/auth/refresh" && method === "POST") {
    return state.signedIn
      ? json(response, { access_token: "access-token-of-the-script" })
      : problem(response, 401, "no session");
  }
  if (!state.signedIn) {
    return problem(response, 401, "no session");
  }

  if (path === "/campaigns" && method === "GET") {
    return json(response, { items: [state.campaign], next: null });
  }
  if (path === `/campaigns/${CAMPAIGN}`) {
    return json(response, state.campaign);
  }
  if (path === `/campaigns/${CAMPAIGN}/plan`) {
    return json(response, plan());
  }
  if (path === `/campaigns/${CAMPAIGN}/gates` && method === "GET") {
    return json(response, { items: [state.gate], next: null });
  }
  if (path === `/campaigns/${CAMPAIGN}/gates/start/approve` && method === "POST") {
    state.gate = { ...state.gate, approvals: 1, approved_by: ["user:dpo"] };
    state.campaign = { ...state.campaign, status: "running" };
    return json(response, { gate: "start", approvals: 1, needed: 1, open: false });
  }
  if (path === `/campaigns/${CAMPAIGN}/progress`) {
    if (state.gate.approvals === 0) {
      return problem(response, 409, "the campaign is not running");
    }
    state.progress = { ...state.progress, done: 2, findings: 1 };
    return json(response, state.progress);
  }

  if (path === "/findings" && method === "GET") {
    const wanted = url.searchParams.get("status");
    const items = !wanted || wanted === state.finding.status ? [state.finding] : [];
    return json(response, { items, next: null });
  }
  if (path === `/findings/${FINDING}` && method === "GET") {
    return json(response, findingDetail());
  }
  if (path === `/findings/${FINDING}/transition` && method === "POST") {
    return body(request).then((sent) => {
      const to = String(sent.to ?? "");
      if (to === "closed_compliant" || to === "reopened") {
        return problem(response, 409, `a finding reaches ${to} only through a re-run: use verify`);
      }
      if (!TRANSITIONS[state.finding.status].includes(to)) {
        return problem(response, 409, `illegal transition ${state.finding.status} -> ${to}`);
      }
      const was = state.finding.status;
      // Declaring it remediated from remediation is what fixes the system here: the re-run below
      // then finds the challenge passing. Nothing the test does by hand changes this.
      if (was === "in_remediation" && to === "pending_verification") {
        state.remediated = true;
      }
      note(to, "user:dpo");
      return json(response, { finding_id: FINDING, from: was, to });
    });
  }
  if (path === `/findings/${FINDING}/verify` && method === "POST") {
    if (state.finding.status !== "pending_verification") {
      return problem(response, 409, "only a finding awaiting verification is re-run");
    }
    // The re-run is what closes it, and only because the challenge passed again.
    note(state.remediated ? "closed_compliant" : "reopened", "system:remediation");
    if (state.remediated) {
      state.campaign = { ...state.campaign, status: "sealed", seal: "abc", seal_verified: true };
    }
    return json(response, { finding_id: FINDING, workflow_id: "remediation-1" });
  }

  if (path === `/evidence/${CAMPAIGN}/chain`) {
    return json(response, {
      artifacts: [{ verdict_id: VERDICT, key: "k", version_id: "1", sha256: "1".repeat(64) }],
      merkle: { root: "a".repeat(64), leaf_count: 1, leaf_order: "verdict_id", tree_key: "t" },
      signature: { key: "s", version_id: "1", sha256: "b".repeat(64), key_id: "argos-evidence", non_production: true },
      time_stamp: { status: "queued", gen_time: null, policy: null, token_key: null },
      journal_report: { key: "j", version_id: "1", sha256: "c".repeat(64) },
    });
  }
  if (path === `/evidence/${CAMPAIGN}/artifacts`) {
    return json(response, {
      items: [{ verdict_id: VERDICT, sha256: "1".repeat(64), created_at: "2026-09-22T11:00:00+00:00" }],
      next: null,
    });
  }
  if (path === `/evidence/${CAMPAIGN}/journal/4242`) {
    return json(response, {
      seq: 4242,
      at: "2026-09-22T09:59:00+00:00",
      actor: "system:probe",
      action: "probe.issued",
      payload: { target: "public.patients", statement: "SHOW ssl" },
      entry_hash: "e".repeat(64),
    });
  }
  if (path === `/evidence/${CAMPAIGN}/dossier.pdf` || path === `/evidence/${CAMPAIGN}/dossier.json`) {
    return json(response, { dossier: "el expediente" }, 200, { "X-Dossier-Sha256": SHA });
  }
  if (path === "/credentials/preview") {
    return json(response, {
      dossier_sha256: SHA,
      credentialSubject: {
        id: `urn:argos:campaign:${CAMPAIGN}`,
        campaignId: CAMPAIGN,
        dossierSha256: SHA,
        merkleRoot: "a".repeat(64),
        units: 2,
        results: { compliant: 2 },
        findingsBySeverity: { high: 1 },
        nonProduction: true,
      },
      withheld: ["approvals", "findings", "texts"],
    });
  }
  if (path === "/credentials" && method === "POST") {
    return body(request).then((sent) => {
      if (sent.dossier_sha256 !== SHA) {
        return problem(response, 409, "the dossier changed since the preview");
      }
      state.credential = "cred-1";
      return json(
        response,
        {
          credential_id: "cred-1",
          revoked: false,
          credential: { credentialSubject: { nonProduction: true } },
        },
        201,
      );
    });
  }
  return problem(response, 404, `no route ${path}`);
}

function statics(request, response, url) {
  const wanted = normalize(url.pathname).replace(/^[\\/]+/, "");
  const file = join(ROOT, wanted);
  const found = file.startsWith(ROOT) && existsSync(file) && statSync(file).isFile();
  const served = found ? file : join(ROOT, "index.html"); // one page, many routes
  response.writeHead(200, { "Content-Type": TYPES[extname(served)] ?? "application/octet-stream" });
  createReadStream(served).pipe(response);
}

createServer((request, response) => {
  const url = new URL(request.url ?? "/", `http://127.0.0.1:${PORT}`);
  if (url.pathname.startsWith("/api/v1")) {
    return api(request, response, url);
  }
  if (url.pathname === "/oidc/realms/argos/protocol/openid-connect/auth") {
    // The realm sends the person back with a code, as Keycloak would.
    const back = new URL(String(url.searchParams.get("redirect_uri")));
    back.search = new URLSearchParams({
      code: CODE,
      state: String(url.searchParams.get("state")),
    }).toString();
    response.writeHead(302, { Location: back.toString() });
    return response.end();
  }
  return statics(request, response, url);
}).listen(PORT, "127.0.0.1", () => {
  process.stdout.write(`the stand-in appliance is listening on http://127.0.0.1:${PORT}\n`);
});
