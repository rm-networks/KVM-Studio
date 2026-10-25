import { expect, test } from "@playwright/test";

// Real mouse clicks: anything covering the assistant (its backdrop) would
// catch them and fail the test.
test("the New Virtual Machine assistant goes from the first page to the last", async ({ page }) => {
  await page.goto("/#token=e2e");
  await page.getByRole("menuitem", { name: "File" }).click();
  await page.getByRole("menuitem", { name: /New Virtual Machine/ }).click();

  const wizard = page.getByRole("dialog", { name: "New Virtual Machine" });
  await expect(wizard).toBeVisible();
  await expect(wizard.getByText("Step 1 of 5")).toBeVisible();

  await wizard.getByRole("button", { name: "Choose…" }).click();
  const picker = page.getByRole("dialog", { name: "Choose an ISO Image" });
  await picker.getByText("alpine-virt-3.22.iso").click();
  await picker.getByRole("button", { name: "Choose", exact: true }).click();
  await expect(picker).toBeHidden();
  await expect(wizard.getByText(/alpine-virt-3\.22\.iso/)).toBeVisible();

  const next = wizard.getByRole("button", { name: "Next >" });
  for (const step of [2, 3, 4, 5]) {
    await next.click();
    await expect(wizard.getByText(`Step ${step} of 5`)).toBeVisible();
  }
  await expect(wizard.getByRole("button", { name: "Finish" })).toBeEnabled();
  await page.screenshot({ path: "test-results/wizard-summary.png" });
});
