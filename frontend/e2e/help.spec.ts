import { expect, test } from "@playwright/test";

test("Help, Documentation opens the project page in a new tab", async ({ page, context }) => {
  await context.route("https://github.com/**", (route) => route.fulfill({ body: "docs" }));
  await page.goto("/#token=e2e");
  await page.getByRole("menuitem", { name: "Help" }).click();
  const popup = page.waitForEvent("popup");
  await page.getByRole("menuitem", { name: "Documentation" }).click();
  expect((await popup).url()).toBe("https://github.com/rm-networks/KVM-Studio");
});
