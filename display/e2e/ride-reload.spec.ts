// S-PW-01: a reload in the middle of a ride, against `wow --sim` (SL-06).
import { expect, test } from "@playwright/test";

test("a reload mid-ride brings the ride screen back within 5 s", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") {
      errors.push(message.text());
    }
  });
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await page.getByRole("button", { name: "Start", exact: true }).click();
  await page.getByRole("button", { name: "Free ride", exact: true }).click();
  const start = page.getByRole("button", { name: "Start ride", exact: true });
  await expect(start).toBeEnabled({ timeout: 30_000 });
  await start.click();
  const pause = page.getByRole("button", { name: "Pause", exact: true });
  await expect(pause).toBeVisible({ timeout: 30_000 });
  await page.reload();
  await expect(pause).toBeVisible({ timeout: 5_000 });
  expect(errors).toEqual([]);
});
