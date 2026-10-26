import { expect, test } from "@playwright/test";

const auth = { Authorization: "Bearer e2e" };

// Real mouse clicks: the library and the tabs follow each other.
test("the library and the tabs select the same VM", async ({ page, request }) => {
  // The VM "test" of the test driver, filed in a folder that starts closed.
  await request.post("/api/library/folders", { headers: auth, data: { path: "Labs" } });
  const vms = (await (await request.get("/api/vms", { headers: auth })).json()) as {
    uuid: string;
    name: string;
  }[];
  const vm = vms.find((v) => v.name === "test");
  expect(vm).toBeTruthy();
  await request.post(`/api/vms/${vm?.uuid}/move`, { headers: auth, data: { folder: "Labs" } });

  await page.goto("/#token=e2e");
  const library = page.getByRole("tree");
  const tabs = page.getByRole("tablist");
  const row = library.getByRole("treeitem", { name: "test" });

  // A click in the library opens the VM's tab and shows it.
  await library.getByRole("treeitem", { name: "Labs" }).getByText("Labs").dblclick();
  await row.click();
  await expect(tabs.getByRole("tab", { name: /test/ })).toHaveAttribute("aria-selected", "true");
  await expect(row).toHaveAttribute("aria-selected", "true");

  // Home: no VM selected.
  await tabs.getByRole("tab", { name: "Home" }).click();
  await expect(row).toHaveAttribute("aria-selected", "false");

  // Its folder closed again, the VM's tab opens it and selects the VM.
  await library.getByRole("treeitem", { name: "Labs" }).getByText("Labs").dblclick();
  await expect(row).toBeHidden();
  await tabs.getByRole("tab", { name: /test/ }).click();
  await expect(row).toBeVisible();
  await expect(row).toHaveAttribute("aria-selected", "true");
});
