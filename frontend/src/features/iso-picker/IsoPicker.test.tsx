import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { NotificationProvider } from "../../components/Notifications";
import { IsoPicker } from "./IsoPicker";

const listing = {
  libraries: [{ name: "ISO principales", path: "/srv/iso", available: true }],
  isos: [
    {
      library: "ISO principales",
      path: "/srv/iso/debian-13.iso",
      relative: "debian-13.iso",
      size: 734003200,
      mtime: 1760000000,
    },
    {
      library: "ISO principales",
      path: "/srv/iso/Windows/Win11.iso",
      relative: "Windows/Win11.iso",
      size: 6442450944,
      mtime: 1750000000,
    },
  ],
};

function mockApi(readable: boolean) {
  vi.stubGlobal(
    "fetch",
    vi.fn((path: string) => {
      if (path === "/api/isos/access/fix") readable = true;
      const body = path.startsWith("/api/isos/access")
        ? {
            path: "/srv/iso/Windows/Win11.iso",
            identity: "qemu",
            readable,
            problems: readable ? [] : [{ kind: "no_search", path: "/srv/iso/Windows" }],
            commands: readable ? [] : ["setfacl -m u:qemu:x /srv/iso/Windows"],
          }
        : listing;
      return Promise.resolve(new Response(JSON.stringify(body)));
    }),
  );
}

afterEach(() => vi.unstubAllGlobals());

function open(onPick = vi.fn()) {
  render(
    <NotificationProvider>
      <IsoPicker onPick={onPick} onClose={() => undefined} />
    </NotificationProvider>,
  );
  return onPick;
}

describe("IsoPicker", () => {
  it("browses folders and picks an image QEMU can read", async () => {
    mockApi(true);
    const onPick = open();
    expect(await screen.findByText("debian-13.iso")).toBeTruthy();
    expect(screen.queryByText("Win11.iso")).toBeNull();
    fireEvent.click(screen.getByText("Windows"));
    fireEvent.click(await screen.findByText("Win11.iso"));
    expect(await screen.findByText("QEMU peut lire cette image.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Choisir" }));
    expect(onPick).toHaveBeenCalledWith("/srv/iso/Windows/Win11.iso");
  });

  it("searches every folder and explains access problems", async () => {
    mockApi(false);
    open();
    await screen.findByText("debian-13.iso");
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "win11" } });
    fireEvent.click(await screen.findByText("Windows/Win11.iso"));
    expect(await screen.findByText(/ne pourra pas lire cette image/)).toBeTruthy();
    expect(screen.getByText("sudo setfacl -m u:qemu:x /srv/iso/Windows")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Corriger" }));
    expect(await screen.findByText("QEMU peut lire cette image.")).toBeTruthy();
  });
});
