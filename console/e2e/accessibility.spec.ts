// Accessibility of what the script goes through: every interactive element can be reached with the
// keyboard and says so when it has the focus. The contrast of the palette is checked against WCAG
// AA in `src/styles/design.test.ts`; here we check the focus nobody sees until they need it.
import { expect, test, type Page } from "@playwright/test";

// The world starts where the script starts: this is the only call a test makes by itself.
test.beforeEach(async ({ request }) => {
  await request.post("/api/v1/__reset");
});

const SCREENS = ["/campaigns", "/findings", "/evidence", "/assistant"];

async function signIn(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page.getByRole("navigation", { name: "Secciones" })).toBeVisible();
}

/** True when the focused element draws something the eye can follow. */
async function focusIsVisible(page: Page) {
  return page.evaluate(() => {
    const focused = document.activeElement;
    if (!focused || focused === document.body) {
      return false;
    }
    const style = getComputedStyle(focused);
    const outline = style.outlineStyle !== "none" && parseFloat(style.outlineWidth) > 0;
    return outline || style.boxShadow !== "none";
  });
}

test("se puede recorrer con el teclado y el foco se ve", async ({ page }) => {
  await signIn(page);
  for (const screen of SCREENS) {
    await page.goto(screen);
    await page.waitForLoadState("networkidle");
    const reachable = await page.locator("a[href], button:not([disabled]), input, select, textarea").count();
    expect(reachable, `${screen} no tiene nada con lo que interactuar`).toBeGreaterThan(0);
    for (let step = 0; step < reachable; step += 1) {
      await page.keyboard.press("Tab");
      expect(await focusIsVisible(page), `${screen}: el elemento ${step + 1} no marca el foco`).toBe(true);
    }
  }
});

test("cada pantalla tiene un encabezado que la nombra", async ({ page }) => {
  await signIn(page);
  for (const screen of SCREENS) {
    await page.goto(screen);
    await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
  }
});
