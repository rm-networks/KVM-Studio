import { type Page, expect, test } from "@playwright/test";

const SIZES = [
  { width: 1280, height: 800 },
  { width: 900, height: 600 },
];

async function openPreferences(page: Page, language: "en" | "fr") {
  await page.route("**/api/info", async (route) => {
    const response = await route.fetch();
    const info = (await response.json()) as { ui: { language: string } };
    info.ui.language = language;
    await route.fulfill({ response, json: info });
  });
  await page.goto("/#token=e2e");
  await page.getByRole("menuitem", { name: language === "fr" ? "Édition" : "Edit" }).click();
  await page.getByRole("menuitem", { name: /Pr[eé]f[eé]rences/ }).click();
  return page.getByRole("dialog");
}

/** Elements of the panel that reach past its right edge, and its horizontal scroll. */
async function overflow(page: Page) {
  return page.locator(".prefs-panel").evaluate((panel) => {
    const right = panel.getBoundingClientRect().right;
    const wide = [...panel.querySelectorAll("*")]
      .filter((el) => el.getBoundingClientRect().right > right + 0.5)
      .map((el) => `${el.tagName.toLowerCase()}.${el.className}`);
    return { scroll: panel.scrollWidth - panel.clientWidth, wide };
  });
}

for (const language of ["en", "fr"] as const) {
  for (const size of SIZES) {
    test(`preferences fit their window (${language}, ${size.width}x${size.height})`, async ({
      page,
    }) => {
      await page.setViewportSize(size);
      const dialog = await openPreferences(page, language);
      const tabs = dialog.getByRole("tab");
      const count = await tabs.count();
      expect(count).toBeGreaterThanOrEqual(6);
      for (let i = 0; i < count; i++) {
        await tabs.nth(i).click();
        const name = (await tabs.nth(i).textContent()) ?? "";
        if (process.env.PREFS_SHOTS) {
          await dialog.screenshot({
            path: `test-results/test-prefs-${language}-${size.width}-${i}.png`,
          });
        }
        expect(await overflow(page), name).toEqual({ scroll: 0, wide: [] });
      }
    });
  }
}

test("the VM tab bar hides and comes back without a restart", async ({ page }) => {
  await page.goto("/#token=e2e");
  await expect(page.getByRole("tab", { name: "Home" })).toBeVisible();
  const toggle = async () => {
    await page.getByRole("menuitem", { name: "Edit" }).click();
    await page.getByRole("menuitem", { name: /Preferences/ }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByRole("tab", { name: "Interface" }).click();
    await dialog.getByLabel("Show the tab bar of the virtual machines").click();
    await dialog.getByRole("button", { name: "OK" }).click();
    await expect(dialog).toBeHidden();
  };
  await toggle();
  await expect(page.getByRole("tab")).toHaveCount(0);
  await toggle();
  await expect(page.getByRole("tab", { name: "Home" })).toBeVisible();
});

test("a combination is added in Hotkeys, then the default list comes back", async ({ page }) => {
  await page.goto("/#token=e2e");
  await page.getByRole("menuitem", { name: "Edit" }).click();
  await page.getByRole("menuitem", { name: /Preferences/ }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("tab", { name: "Hotkeys" }).click();
  await dialog.getByRole("button", { name: "Add" }).click();
  await dialog.getByLabel("Win").click();
  await dialog.locator(".prefs-subform select").selectOption("E");
  await dialog.getByLabel("Name").fill("test-explorer");
  await dialog.getByRole("button", { name: "Add" }).nth(1).click();
  if (process.env.PREFS_SHOTS) await dialog.screenshot({ path: "test-results/test-hotkeys.png" });
  await dialog.getByRole("button", { name: "OK" }).click();
  await expect(dialog).toBeHidden();

  // Back to the default list.
  await page.getByRole("menuitem", { name: "Edit" }).click();
  await page.getByRole("menuitem", { name: /Preferences/ }).click();
  await dialog.getByRole("tab", { name: "Hotkeys" }).click();
  await expect(dialog.getByRole("option", { name: /test-explorer/ })).toBeVisible();
  await dialog.getByRole("button", { name: "Restore Defaults" }).click();
  await expect(dialog.getByRole("option", { name: /test-explorer/ })).toHaveCount(0);
  await dialog.getByRole("button", { name: "OK" }).click();
});
