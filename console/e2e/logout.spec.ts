// Closing the session on a shared desk (security review F09-02, SEC-041): after «Salir» and a
// reload, the console asks to sign in again. Only clicks, as in the rest of the scripts.
import { expect, test } from "@playwright/test";

test.beforeEach(async ({ request }) => {
  await request.post("/api/v1/__reset");
});

test("salir y recargar no deja la sesión abierta", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page.getByRole("navigation", { name: "Secciones" })).toBeVisible();

  await page.getByRole("button", { name: "Salir" }).click();
  await expect(page.getByRole("button", { name: "Entrar" })).toBeVisible();

  await page.reload();
  await expect(page.getByRole("button", { name: "Entrar" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Secciones" })).toHaveCount(0);
});
