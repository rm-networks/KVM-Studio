import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { NotificationProvider } from "../../components/Notifications";
import { makeVm } from "../../test/fixtures";
import { GuestToolsDialog } from "./GuestToolsDialog";

const COMMAND =
  'sudo sh -c \'m=$(mktemp -d) && mount -o ro -L KS_TOOLS "$m" && sh "$m/install.sh"\'';

function mockApi(info: object, responding: boolean, insertResult: object = {}) {
  const posts: { path: string; body: unknown }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((path: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        posts.push({ path, body: init.body ? JSON.parse(init.body as string) : null });
        const answer = path.endsWith("/eject")
          ? { drives: ["sda"] }
          : { drive: "sda", restart_required: false, installer: null, ...insertResult };
        return Promise.resolve(new Response(JSON.stringify(answer)));
      }
      const body = path.endsWith("/agent") ? { responding } : info;
      return Promise.resolve(new Response(JSON.stringify(body)));
    }),
  );
  return posts;
}

const info = (extra: object = {}) => ({
  active: true,
  family: "linux",
  agent: false,
  inserted: false,
  virtio_win: null,
  virtio_state: "unset",
  linux_command: COMMAND,
  ...extra,
});

const show = (onClose = () => {}) =>
  render(
    <NotificationProvider>
      <GuestToolsDialog
        vm={makeVm({ uuid: "u1", name: "deb", state: "running" })}
        onClose={onClose}
      />
    </NotificationProvider>,
  );

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("GuestToolsDialog", () => {
  it("inserts the CD, shows the command to copy, waits for the agent, then ejects", async () => {
    const posts = mockApi(info(), true);
    const write = vi.fn(() => Promise.resolve());
    vi.stubGlobal("pywebview", { api: { write_clipboard: write } });
    const onClose = vi.fn();
    show(onClose);
    const insert = await screen.findByRole("button", { name: "Insérer le CD des outils" });
    await vi.waitFor(() => expect((insert as HTMLButtonElement).disabled).toBe(false));
    vi.useFakeTimers({ shouldAdvanceTime: true });
    fireEvent.click(insert);
    expect(await screen.findByText("1. Le CD KS_TOOLS est dans le lecteur sda.")).toBeTruthy();
    expect(screen.getByText(COMMAND)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Copier" }));
    await vi.waitFor(() => expect(write).toHaveBeenCalledWith(COMMAND));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(
      await screen.findByText("3. L'agent invité répond : les outils sont installés."),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Éjecter le CD" }));
    await vi.waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(posts.map((p) => p.path)).toEqual([
      "/api/vms/u1/guest-tools",
      "/api/vms/u1/guest-tools/eject",
    ]);
    expect(posts[0]?.body).toEqual({ family: "linux" });
  });

  it.each([
    ["unset", null, /Aucune ISO virtio-win n'est configurée/],
    ["missing", "/iso/virtio-win.iso", /Cette ISO virtio-win n'existe plus/],
    ["outside", "/home/me/virtio-win.iso", /n'est pas dans une bibliothèque ISO/],
  ])("explains a %s virtio-win ISO and blocks the insertion", async (state, path, message) => {
    mockApi(info({ family: "windows", virtio_state: state, virtio_win: path }), false);
    show();
    expect(await screen.findByText(message)).toBeTruthy();
    expect(
      (screen.getByRole("button", { name: "Insérer le CD des outils" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    const add = screen.queryByRole("button", {
      name: "Ajouter son dossier comme bibliothèque ISO…",
    });
    expect(add !== null).toBe(state === "outside");
    if (add) {
      fireEvent.click(add);
      expect(((await screen.findByDisplayValue("/home/me")) as HTMLInputElement).value).toBe(
        "/home/me",
      );
    }
  });

  it("shows each Windows step, and the power cycle a new drive needs", async () => {
    mockApi(
      info({ family: "windows", virtio_state: "ok", virtio_win: "/iso/virtio-win.iso" }),
      false,
      {
        drive: "sdb",
        restart_required: true,
        installer: "virtio-win-guest-tools.exe",
      },
    );
    show();
    const insert = await screen.findByRole("button", { name: "Insérer le CD des outils" });
    await vi.waitFor(() => expect((insert as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(insert);
    expect(
      await screen.findByText(
        "1. virtio-win-guest-tools.exe est copié de l'ISO virtio-win sur le CD.",
      ),
    ).toBeTruthy();
    expect(
      screen.getByText(/2\. Le CD KS_TOOLS est dans le lecteur sdb, que la VM allumée/),
    ).toBeTruthy();
    expect(screen.getByText(/Un redémarrage depuis l'invité ne suffit pas/)).toBeTruthy();
  });

  it("goes straight to the steps when the CD is already in", async () => {
    mockApi(info({ inserted: true }), false);
    show();
    expect(await screen.findByText("1. Le CD est inséré.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Éjecter le CD" })).toBeTruthy();
  });
});
