// ADR-0013 · the types of the console come from the v1 contract; if they fall behind, this fails.
// It regenerates them from services/api/openapi.json and compares with the versioned file.
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const versioned = "src/api/schema.d.ts";
const scratch = mkdtempSync(join(tmpdir(), "argos-api-types-"));
const fresh = join(scratch, "schema.d.ts");
try {
  execFileSync(
    process.execPath,
    ["node_modules/openapi-typescript/bin/cli.js", "../services/api/openapi.json", "-o", fresh],
    { stdio: "ignore" },
  );
  const normalise = (text) => text.replace(/\r\n/g, "\n");
  if (normalise(readFileSync(fresh, "utf-8")) !== normalise(readFileSync(versioned, "utf-8"))) {
    console.error(`${versioned} is behind the v1 contract: run \`npm run api:types\``);
    process.exit(1);
  }
  console.log("the console types match the v1 contract");
} finally {
  rmSync(scratch, { recursive: true, force: true });
}
