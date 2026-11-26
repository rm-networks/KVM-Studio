import { type Page, expect, test } from "@playwright/test";

// Every screen reached from the menus must work under the Content Security
// Policy the backend sends: any violation fails the test.

// Left out: actions that end or change something, and the View settings that
// are saved and would reach the other tests running at the same time.
const SKIP =
  /Quit|Exit|Close|Power|Shut|Restart|Suspend|Reset|Delete|Remove|Documentation|Uninstall|Window Mode|Desktop|Log ?out|Revert|Take Snapshot|Send|Full Screen|Unity|Pause|Resume|Ctrl|Grab|Language|English|Français|Library|Toolbar|Status Bar|Customize|Autofit/i;

async function watchPolicy(page: Page): Promise<string[]> {
  const violations: string[] = [];
  page.on("console", (message) => {
    if (/Content Security Policy/i.test(message.text())) violations.push(message.text());
  });
  await page.addInitScript(() => {
    document.addEventListener("securitypolicyviolation", (event) => {
      console.error(`Content Security Policy: ${event.violatedDirective} ${event.blockedURI}`);
    });
  });
  return violations;
}

async function closeAll(page: Page) {
  for (let i = 0; i < 3; i++) await page.keyboard.press("Escape");
}

test("menus and dialogs run under the Content Security Policy", async ({ page }) => {
  const violations = await watchPolicy(page);
  const answer = await page.goto("/#token=e2e");
  expect(answer?.headers()["content-security-policy"]).toContain("script-src 'self'");
  // The VM of the test driver, wherever another test filed it.
  await page.getByPlaceholder("Search").fill("test");
  await page
    .getByRole("treeitem", { name: /\btest\b/ })
    .first()
    .click();

  const menus = await page.getByRole("menubar").getByRole("menuitem").allInnerTexts();
  expect(menus.length).toBeGreaterThan(3);
  for (const menu of menus) {
    await page.getByRole("menubar").getByRole("menuitem", { name: menu, exact: true }).click();
    const items = await page.getByRole("menu").getByRole("menuitem").allInnerTexts();
    await closeAll(page);
    for (const item of items.map((i) => i.split("\n")[0]?.trim() ?? "")) {
      if (!item || SKIP.test(item)) continue;
      await page.getByRole("menubar").getByRole("menuitem", { name: menu, exact: true }).click();
      const entry = page.getByRole("menu").getByRole("menuitem", { name: item }).first();
      if (await entry.isDisabled()) {
        await closeAll(page);
        continue;
      }
      await entry.click();
      await page.waitForTimeout(300);
      await closeAll(page);
    }
  }
  expect(violations).toEqual([]);
});
