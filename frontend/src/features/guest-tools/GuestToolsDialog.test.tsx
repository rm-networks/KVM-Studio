import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { NotificationProvider } from "../../components/Notifications";
import { makeVm } from "../../test/fixtures";
import { GuestToolsDialog } from "./GuestToolsDialog";

function mockApi(info: object, responding: boolean) {
  const posts: unknown[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((path: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        posts.push(JSON.parse(init.body as string));
        return Promise.resolve(new Response(JSON.stringify({ typed: true, drive: null })));
      }
      const body = path.endsWith("/agent") ? { responding } : info;
      return Promise.resolve(new Response(JSON.stringify(body)));
    }),
  );
  return posts;
}

const render_ = (state: "running" | "shutoff" = "running") =>
  render(
    <NotificationProvider>
      <GuestToolsDialog vm={makeVm({ uuid: "u1", name: "Win11", state })} onClose={() => {}} />
    </NotificationProvider>,
  );

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("GuestToolsDialog", () => {
  it("types the command with the remembered layout, then waits for the agent", async () => {
    const posts = mockApi(
      { active: true, family: "linux", layout: "us", agent: false, virtio_win: null },
      true,
    );
    render_();
    await screen.findByDisplayValue("Anglais US (QWERTY)");
    vi.useFakeTimers({ shouldAdvanceTime: true });
    fireEvent.click(screen.getByRole("button", { name: "Installer" }));
    await screen.findByText(/Commande tapée/);
    expect(posts).toEqual([{ family: "linux", layout: "us" }]);
    vi.advanceTimersByTime(5000);
    await screen.findByText(/l'agent répond/);
  });

  it("asks for the virtio-win ISO for Windows guests", async () => {
    mockApi(
      { active: true, family: "windows", layout: null, agent: false, virtio_win: null },
      false,
    );
    render_();
    await screen.findByText(/Aucune ISO virtio-win/);
    expect(screen.getByRole<HTMLButtonElement>("button", { name: "Installer" }).disabled).toBe(
      true,
    );
  });

  it("needs a running VM", async () => {
    mockApi({ active: false, family: null, layout: null, agent: false, virtio_win: null }, false);
    render_("shutoff");
    await screen.findByText(/Démarrez la machine virtuelle/);
    await waitFor(() =>
      expect(screen.getByRole<HTMLButtonElement>("button", { name: "Installer" }).disabled).toBe(
        true,
      ),
    );
  });
});
