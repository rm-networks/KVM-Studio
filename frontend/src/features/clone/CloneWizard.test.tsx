import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { NotificationProvider } from "../../components/Notifications";
import { makeVm } from "../../test/fixtures";
import { VmActionsProvider } from "../vm/VmActions";
import { useVmActions } from "../vm/vmActionsContext";
import { CloneWizard } from "./CloneWizard";

const source = makeVm({ uuid: "src", name: "web" });

function mockApi(final: "done" | "cancelled" = "done") {
  const posts: { path: string; body: unknown }[] = [];
  let polls = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn((path: string, init?: RequestInit) => {
      const body = init?.body ? (JSON.parse(init.body as string) as unknown) : undefined;
      if (init?.method === "POST") posts.push({ path, body });
      const task = (state: string, progress: number) => ({
        id: "t1",
        kind: "clone",
        state,
        progress,
        step: "web-clone.qcow2",
        result: state === "done" ? { uuid: "new", name: "web-clone", warnings: [] } : {},
        error_code: null,
        error_detail: null,
      });
      let answer: unknown;
      if (path === "/api/library") answer = { root: "/srv/vm/KVM-Studio/VM", folders: ["Labs"] };
      else if (path === "/api/vms") answer = [source];
      else if (path === "/api/vms/src/clone") answer = task("running", 0.1);
      else if (path === "/api/tasks/t1/cancel") answer = task("cancelled", 0.3);
      else if (path === "/api/tasks/t1")
        answer = ++polls < 2 ? task("running", 0.5) : task(final, 1);
      return Promise.resolve(new Response(JSON.stringify(answer)));
    }),
  );
  return posts;
}

afterEach(() => vi.unstubAllGlobals());

function open(vm = source) {
  const onClose = vi.fn();
  render(
    <NotificationProvider>
      <CloneWizard source={vm} onClose={onClose} />
    </NotificationProvider>,
  );
  return onClose;
}

const next = () => fireEvent.click(screen.getByRole("button", { name: "Suivant >" }));

describe("CloneWizard", () => {
  it("goes through the pages and follows the copy", async () => {
    const posts = mockApi();
    open();
    expect(screen.getByText("Étape 1 sur 6")).toBeTruthy();
    next();
    fireEvent.click(screen.getByLabelText("Clone lié"));
    next();
    expect(await screen.findByDisplayValue("web-clone")).toBeTruthy();
    next();
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "Labs" } });
    expect(screen.getByText("/srv/vm/KVM-Studio/VM/Labs/web-clone")).toBeTruthy();
    next();
    expect(screen.getByText(/demande une confirmation avant de démarrer/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Cloner" }));
    expect(await screen.findByRole("progressbar", { name: "" })).toBeTruthy();
    expect(await screen.findByText("« web-clone » est prête.", {}, { timeout: 3000 })).toBeTruthy();
    expect(posts).toEqual([
      { path: "/api/vms/src/clone", body: { kind: "linked", name: "web-clone", folder: "Labs" } },
    ]);
  });

  it("needs a powered off source", () => {
    mockApi();
    open(makeVm({ uuid: "src", name: "web", state: "running" }));
    expect(screen.getByText(/seule une machine éteinte peut être clonée/)).toBeTruthy();
    expect((screen.getByRole("button", { name: "Suivant >" }) as HTMLButtonElement).disabled).toBe(
      true,
    );
  });

  it("cancels the copy", async () => {
    const posts = mockApi("cancelled");
    open();
    for (let i = 0; i < 4; i++) {
      await waitFor(() =>
        expect(
          (screen.getByRole("button", { name: "Suivant >" }) as HTMLButtonElement).disabled,
        ).toBe(false),
      );
      next();
    }
    fireEvent.click(screen.getByRole("button", { name: "Cloner" }));
    const cancel = await screen.findByRole("button", { name: "Annuler" });
    await waitFor(() => expect((cancel as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(cancel);
    expect(await screen.findByText(/Le clonage a été annulé/)).toBeTruthy();
    expect(posts.map((p) => p.path)).toContain("/api/tasks/t1/cancel");
  });
});

function Starter() {
  const actions = useVmActions();
  return (
    <button type="button" onClick={() => actions.power(source, "start")}>
      start
    </button>
  );
}

describe("starting a source of linked clones", () => {
  it("asks first, then starts it on purpose", async () => {
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((path: string) => {
        calls.push(path);
        if (path.endsWith("force=true"))
          return Promise.resolve(new Response(null, { status: 204 }));
        const error = {
          error: { code: "vm.has_linked_clones", detail: "Linked clones depend on it: web-clone" },
        };
        return Promise.resolve(new Response(JSON.stringify(error), { status: 409 }));
      }),
    );
    render(
      <NotificationProvider>
        <VmActionsProvider>
          <Starter />
        </VmActionsProvider>
      </NotificationProvider>,
    );
    fireEvent.click(screen.getByText("start"));
    expect(await screen.findByText(/servent de base à ces clones liés : web-clone/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Démarrer quand même" }));
    await waitFor(() => expect(calls).toHaveLength(2));
    expect(calls[1]).toBe("/api/vms/src/power/start?force=true");
  });
});
