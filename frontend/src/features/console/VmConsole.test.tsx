import { act, fireEvent, render, screen } from "@testing-library/react";
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

beforeEach(() => {
  instances.length = 0;
  window.pywebview = { api: desktopApi };
  sessionStorage.setItem("kvmstudio.token", "tok");
});

afterEach(() => {
  delete window.pywebview;
  vi.clearAllMocks();
});

describe("VmConsole", () => {
  it("connects with the token as a WebSocket subprotocol", () => {
    render(<VmConsole uuid="abc" />);
    const rfb = rfbAt(0);
    expect(rfb.url).toBe(`ws://${window.location.host}/api/vms/abc/console`);
    expect(rfb.options.wsProtocols).toEqual(["binary", "kvmstudio.tok"]);
    expect(screen.getByText("Connexion à la console…")).toBeTruthy();
    act(() => void rfb.dispatchEvent(new Event("connect")));
    expect(screen.queryByText("Connexion à la console…")).toBeNull();
  });

  it("puts guest clipboard text on the host clipboard", () => {
    render(<VmConsole uuid="abc" />);
    const event = new CustomEvent("clipboard", { detail: { text: "Copié dans la VM" } });
    act(() => void rfbAt(0).dispatchEvent(event));
    expect(desktopApi.write_clipboard).toHaveBeenCalledWith("Copié dans la VM");
  });

  it("sends the host clipboard before replaying Ctrl+V", async () => {
    vi.useFakeTimers();
    const { container } = render(<VmConsole uuid="abc" />);
    const rfb = rfbAt(0);
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

  it("offers a reconnect button after a disconnect", () => {
    render(<VmConsole uuid="abc" />);
    act(() => void rfbAt(0).dispatchEvent(new Event("disconnect")));
    fireEvent.click(screen.getByRole("button", { name: "Reconnecter" }));
    expect(rfbAt(0).disconnected).toBe(true);
    expect(instances).toHaveLength(2);
  });
});
