// ARG-080 · the golden rule is enforced by the linter, and a misuse planted here proves it bites.
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import stylelint from "stylelint";

import config from "../../stylelint.config.mjs";

const HERE = join(process.cwd(), "src", "styles");

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((at) => {
    const channel = Number.parseInt(hex.slice(at, at + 2), 16) / 255;
    return channel <= 0.03928 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
  }) as [number, number, number];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a: string, b: string): number {
  const [light, dark] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (light + 0.05) / (dark + 0.05);
}

async function problems(code: string, file: string): Promise<string[]> {
  const result = await stylelint.lint({ code, codeFilename: join(process.cwd(), file), config });
  return (result.results[0]?.warnings ?? []).map((w) => w.rule);
}

describe("the design system", () => {
  it("refuses gold outside what is accredited: the planted misuse fails", async () => {
    const planted = ".button-primary { background: var(--gold); }";
    expect(await problems(planted, "src/components/Button.css")).toContain(
      "declaration-property-value-disallowed-list",
    );
  });

  it("refuses the raw gold too, however it is written", async () => {
    const planted = ".banner { border-color: #C9A227; }";
    expect(await problems(planted, "src/components/Banner.css")).not.toEqual([]);
  });

  it("allows gold where the verdict and the credential are drawn", async () => {
    const allowed = ".verdict-accredited { color: var(--gold); }";
    expect(await problems(allowed, "src/styles/accredited.css")).toEqual([]);
  });

  it("lets no component declare a colour of its own", async () => {
    expect(await problems(".x { color: #ffffff; }", "src/components/X.css")).toContain(
      "color-no-hex",
    );
    expect(await problems(".x { color: rgb(1, 2, 3); }", "src/components/X.css")).toContain(
      "function-disallowed-list",
    );
  });

  it("keeps the palette the brand fixed: dark skin, teal action, severities and gold", () => {
    const tokens = readFileSync(join(HERE, "tokens.css"), "utf-8");
    for (const name of ["--bg", "--panel", "--accent", "--sev-critical", "--sev-high", "--sev-medium", "--sev-low", "--gold"]) {
      expect(tokens).toContain(`${name}:`);
    }
    expect(tokens.toUpperCase()).toContain("#C9A227");
  });

  it("every text pair of the palette reaches WCAG AA (4.5:1)", () => {
    const tokens = Object.fromEntries(
      [...readFileSync(join(HERE, "tokens.css"), "utf-8").matchAll(/(--[\w-]+):\s*(#[0-9A-Fa-f]{6})/g)].map(
        (match) => [match[1], match[2]],
      ),
    ) as Record<string, string>;
    const pairs: Array<[string, string]> = [
      ["--text", "--bg"],
      ["--text", "--panel"],
      ["--text", "--panel-2"],
      ["--text-muted", "--panel"],
      ["--on-accent", "--accent"],
      ["--on-accent", "--accent-strong"],
      ["--on-accent", "--sev-critical"],
      ["--on-light", "--sev-high"],
      ["--on-light", "--sev-medium"],
      ["--on-light", "--gold"],
      ["--gold", "--panel"],
      ["--accent-hi", "--panel"],
    ];
    for (const [text, surface] of pairs) {
      expect(contrast(tokens[text]!, tokens[surface]!), `${text} on ${surface}`).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("the stylesheets of the console pass their own rules", async () => {
    for (const name of readdirSync(HERE).filter((file: string) => file.endsWith(".css"))) {
      const code = readFileSync(join(HERE, name), "utf-8");
      expect(await problems(code, `src/styles/${name}`), name).toEqual([]);
    }
  });
});
