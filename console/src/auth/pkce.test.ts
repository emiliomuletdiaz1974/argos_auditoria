// ARG-073 · PKCE (RFC 7636): the verifier stays in the browser, only its challenge travels.
import { createHash } from "node:crypto";

import { challengeOf, newVerifier } from "./pkce";

const UNRESERVED = /^[A-Za-z0-9\-._~]+$/;

describe("PKCE", () => {
  it("draws a verifier of the length and alphabet the RFC asks for", () => {
    const verifier = newVerifier();
    expect(verifier.length).toBeGreaterThanOrEqual(43);
    expect(verifier.length).toBeLessThanOrEqual(128);
    expect(verifier).toMatch(UNRESERVED);
    expect(newVerifier()).not.toEqual(verifier);
  });

  it("derives the S256 challenge exactly as another implementation does", async () => {
    const verifier = newVerifier();
    const expected = createHash("sha256").update(verifier).digest("base64url");
    await expect(challengeOf(verifier)).resolves.toEqual(expected);
  });
});
