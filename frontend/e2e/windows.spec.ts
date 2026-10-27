import { type Locator, type Page, expect, test } from "@playwright/test";

async function dragBy(page: Page, bar: Locator, dx: number, dy: number) {
  const box = await bar.boundingBox();
  if (!box) throw new Error("no title bar");
  const x = box.x + box.width / 3;
  const y = box.y + box.height / 2;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x + dx / 2, y + dy / 2, { steps: 4 });
  await page.mouse.move(x + dx, y + dy, { steps: 4 });
  await page.mouse.up();
}

async function expectMoved(page: Page, dialog: Locator, bar: Locator) {
  const before = await dialog.boundingBox();
  await dragBy(page, bar, -150, -60);
  const after = await dialog.boundingBox();
  expect(Math.round((after?.x ?? 0) - (before?.x ?? 0))).toBe(-150);
  expect(Math.round((after?.y ?? 0) - (before?.y ?? 0))).toBe(-60);
}

// Real mouse drags on the title bar of the windows over the main one.
test("windows over the main one move by their title bar", async ({ page }) => {
  await page.goto("/#token=e2e");

  await page.getByRole("menuitem", { name: "Edit" }).click();
  await page.getByRole("menuitem", { name: "Preferences…" }).click();
  const prefs = page.getByRole("dialog");
  await expectMoved(page, prefs, prefs.locator(".dialog-titlebar"));
  await page.keyboard.press("Escape");
  await expect(prefs).toBeHidden();

  await page.getByRole("menuitem", { name: "Edit" }).click();
  await page.getByRole("menuitem", { name: /Virtual Network Editor/ }).click();
  const editor = page.getByRole("dialog");
  await expectMoved(page, editor, editor.locator(".dialog-titlebar"));
  await page.keyboard.press("Escape");

  // From the library: New Virtual Machine in the folder right-clicked.
  await page.getByText("My Computer").click({ button: "right" });
  await page.getByRole("menuitem", { name: /New Virtual Machine/ }).click();
  const wizard = page.getByRole("dialog", { name: "New Virtual Machine" });
  await expect(wizard).toBeVisible();
  await expectMoved(page, wizard, wizard.locator(".wizard-header"));
  await page.screenshot({ path: "test-results/moved-wizard.png" });
});
