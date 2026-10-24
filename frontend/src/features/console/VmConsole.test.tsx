import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { VmConsole } from "./VmConsole";

// vi.mock is hoisted above the imports, so the fake must be hoisted too.
const { FakeRfb, instances } = vi.hoisted(() => {
  const instances: InstanceType<typeof FakeRfb>[] = [];
  class FakeRfb extends EventTarget {
    url: string;
    options: { wsProtocols?: string[] };
    scaleViewport = false;
    focusOnClick = false;
    background = "";
    pasted: string[] = [];
    keys: [number, string | null, boolean][] = [];
    disconnected = false;

    constructor(_target: HTMLElement, url: string, options: { wsProtocols?: string[] }) {
      super();
      this.url = url;
      this.options = options;
      instances.push(this);
    }
    clipboardPasteFrom(text: string) {
      this.pasted.push(text);
    }
    sendKey(keysym: number, code: string | null, down = true) {
      this.keys.push([keysym, code, down]);
    }
    disconnect() {
      this.disconnected = true;
    }
  }
  return { FakeRfb, instances };
});

vi.mock("@novnc/novnc", () => ({ default: FakeRfb }));

function rfbAt(index: number): InstanceType<typeof FakeRfb> {
  const rfb = instances[index];
  if (!rfb) throw new Error(`no RFB instance #${index}`);
  return rfb;
}

const desktopApi = {
  read_clipboard: vi.fn(() => Promise.resolve("Grüße, été 2026")),
  write_clipboard: vi.fn(() => Promise.resolve()),
};

let display = { live: ["vnc"], config: ["vnc"], clipboard: true, active: true };
const posts: string[] = [];

beforeEach(() => {
  instances.length = 0;
  posts.length = 0;
  display = { live: ["vnc"], config: ["vnc"], clipboard: true, active: true };
  window.pywebview = { api: desktopApi };
  sessionStorage.setItem("kvmstudio.token", "tok");
  vi.stubGlobal(
    "fetch",
    vi.fn((path: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        posts.push(path);
        display = { ...display, config: [...display.config, "vnc"] };
        return Promise.resolve(new Response(JSON.stringify({ restart_required: true })));
      }
      return Promise.resolve(new Response(JSON.stringify(display)));
    }),
  );
});

afterEach(() => {
  delete window.pywebview;
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

async function connected(): Promise<InstanceType<typeof FakeRfb>> {
  await waitFor(() => expect(instances.length).toBeGreaterThan(0));
  return rfbAt(0);
}

describe("VmConsole", () => {
  it("connects with the token as a WebSocket subprotocol", async () => {
    render(<VmConsole uuid="abc" />);
    const rfb = await connected();
    expect(rfb.url).toBe(`ws://${window.location.host}/api/vms/abc/console`);
    expect(rfb.options.wsProtocols).toEqual(["binary", "kvmstudio.tok"]);
    expect(screen.getByText("Connexion à la console…")).toBeTruthy();
    act(() => void rfb.dispatchEvent(new Event("connect")));
    expect(screen.queryByText("Connexion à la console…")).toBeNull();
  });

  it("puts guest clipboard text on the host clipboard", async () => {
    render(<VmConsole uuid="abc" />);
    const rfb = await connected();
    const event = new CustomEvent("clipboard", { detail: { text: "Copié dans la VM" } });
    act(() => void rfb.dispatchEvent(event));
    expect(desktopApi.write_clipboard).toHaveBeenCalledWith("Copié dans la VM");
  });

  it("sends the host clipboard before replaying Ctrl+V", async () => {
    const { container } = render(<VmConsole uuid="abc" />);
    const rfb = await connected();
    vi.useFakeTimers();
    const screenEl = container.querySelector(".console-screen");
    if (!screenEl) throw new Error("no console screen");

    fireEvent.keyDown(screenEl, { key: "v", code: "KeyV", ctrlKey: true });
    await vi.runAllTimersAsync();

    expect(rfb.pasted).toEqual(["Grüße, été 2026"]);
    expect(rfb.keys).toEqual([
      [0x76, "KeyV", true],
      [0x76, "KeyV", false],
    ]);
    vi.useRealTimers();
  });

  it("offers a reconnect button after a disconnect", async () => {
    render(<VmConsole uuid="abc" />);
    const rfb = await connected();
    act(() => void rfb.dispatchEvent(new Event("disconnect")));
    fireEvent.click(screen.getByRole("button", { name: "Reconnecter" }));
    expect(rfb.disconnected).toBe(true);
    expect(instances).toHaveLength(2);
  });

  it("gives up waiting after a while", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    render(<VmConsole uuid="abc" />);
    await connected();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(16_000);
    });
    expect(screen.getByText("La console ne répond pas.")).toBeTruthy();
    vi.useRealTimers();
  });

  it("explains a SPICE-only VM and adds a VNC display", async () => {
    display = { live: ["spice"], config: ["spice"], clipboard: false, active: true };
    render(<VmConsole uuid="abc" />);
    expect(await screen.findByText(/n'a qu'un affichage SPICE/)).toBeTruthy();
    expect(instances).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Ajouter un affichage VNC" }));
    fireEvent.click(
      screen.getAllByRole("button", { name: "Ajouter un affichage VNC" }).at(-1) as HTMLElement,
    );
    expect(await screen.findByText(/Arrêtez puis redémarrez/)).toBeTruthy();
    expect(posts).toEqual(["/api/vms/abc/display/vnc"]);
  });
});
