// The script of the phase, end to end and only through the console: sign in, read the plan before
// anything runs, approve the gate, follow the run, triage the finding, declare it remediated, ask
// for the re-run, and see that it closes because the challenge passed again — never by a button.
// At the end, the evidence of the campaign and its credential.
//
// The rule of this file: no request is made from the test. Everything happens by clicking.
import { expect, test } from "@playwright/test";

// The world starts where the script starts: this is the only call a test makes by itself.
test.beforeEach(async ({ request }) => {
  await request.post("/api/v1/__reset");
});

const CAMPAIGN = "0192b000-0000-7000-8000-000000000001";
const FINDING = "0192c000-0000-7000-8000-000000000001";

test("de la campaña al cierre verificado de un hallazgo", async ({ page }) => {
  await test.step("entrar", async () => {
    await page.goto("/");
    await page.getByRole("button", { name: "Entrar" }).click();
    await expect(page.getByRole("navigation", { name: "Secciones" })).toBeVisible();
  });

  await test.step("leer el plan previo antes de que corra nada", async () => {
    await page.getByRole("link", { name: "Campañas" }).click();
    await page.getByRole("link", { name: "Campaña de otoño" }).click();
    const plan = page.getByRole("region", { name: "Plan previo" });
    await expect(plan).toContainText("SHOW ssl");
    await expect(plan).toContainText("Ninguna sonda se ha ejecutado todavía");
  });

  await test.step("aprobar la compuerta y seguir el progreso", async () => {
    await page.getByRole("button", { name: "Aprobar" }).click();
    await expect(page.getByLabel("Compuertas")).toContainText("Con la aprobación de user:dpo");
    await page.reload();
    await expect(page.getByRole("region", { name: "Progreso" })).toContainText("2 de 2 unidades");
  });

  await test.step("triar el hallazgo y leer su porqué", async () => {
    await page.getByRole("link", { name: "Hallazgos" }).click();
    await expect(page.getByRole("cell", { name: "Alta" })).toBeVisible();
    await page.getByRole("link", { name: "sec-encryption-in-transit" }).click();
    const why = page.getByRole("region", { name: "Por qué" });
    await expect(why).toContainText("off");
    await expect(why).toContainText("RGPD · art. 32.1.a");
    await expect(why.getByRole("link", { name: /asiento 4242/ })).toHaveAttribute(
      "href",
      `/evidence/${CAMPAIGN}#journal-4242`,
    );
  });

  await test.step("no hay forma de cerrarlo a mano", async () => {
    await expect(page.getByRole("button", { name: /cerrar/i })).toHaveCount(0);
    const actions = page.getByRole("group", { name: "Acciones" });
    await expect(actions.getByRole("button")).toHaveText(["Pasar a remediación", "Aceptar el riesgo"]);
  });

  await test.step("remediar y declararlo subsanado", async () => {
    await page.getByRole("button", { name: "Pasar a remediación" }).click();
    await page.getByRole("button", { name: "Marcar como subsanado" }).click();
    await expect(page.getByRole("group", { name: "Acciones" })).toHaveCount(0);
    await expect(page.getByText("Solo la reejecución del reto")).toBeVisible();
  });

  await test.step("la reejecución lo cierra porque el reto vuelve a pasar", async () => {
    await page.getByRole("button", { name: "Volver a ejecutar el reto" }).click();
    await expect(page.getByRole("status")).toContainText("Reejecución en marcha");
    await page.goto(`/findings/${FINDING}`);
    // Closed, and closed by the re-run: the last step of its history is the system's, not a person's.
    await expect(page.getByText("Cerrado conforme").first()).toBeVisible();
    const last = page.getByRole("list", { name: "Historia" }).getByRole("listitem").last();
    await expect(last).toContainText("system:remediation");
    await expect(last).toContainText("Cerrado conforme");
    await expect(page.getByRole("group", { name: "Acciones" })).toHaveCount(0);
  });

  await test.step("la evidencia y su credencial", async () => {
    await page.goto(`/evidence/${CAMPAIGN}#journal-4242`);
    await expect(page.getByRole("region", { name: "Asiento 4242 del diario" })).toContainText("SHOW ssl");
    const chain = page.getByRole("list", { name: "Eslabones" });
    await expect(chain.getByRole("listitem", { name: "Firma" })).toContainText("clave de desarrollo");
    await expect(chain.getByRole("listitem", { name: "Sello de tiempo" })).toContainText("En cola");
    await page.getByLabel(/He revisado/).check();
    await page.getByRole("button", { name: "Emitir la credencial" }).click();
    await expect(page.getByText("Credencial de desarrollo")).toBeVisible();
  });
});
