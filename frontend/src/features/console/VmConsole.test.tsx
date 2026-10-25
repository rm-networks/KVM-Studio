import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { noteStart } from "./bootSplash";
import { type ConsoleHandle, useConsole } from "./consoleRegistry";
import { COMBOS } from "./keys";
import { VmConsole } from "./VmConsole";

function Probe() {
  const handle: ConsoleHandle | null = useConsole("abc");
  const f2 = COMBOS.find((c) => c.id === "ctrl-alt-f2");
  return (
    <div data-testid="probe" data-ready={handle ? "yes" : "no"}>
      <button onClick={() => handle?.sendCtrlAltDel()}>cad</button>
      <button onClick={() => handle?.sendKeys(f2?.keys ?? [])}>f2</button>
    </div>
  );
}

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
    cad = 0;
    sendCtrlAltDel() {
      this.cad += 1;
    }
    focus() {}
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

const vncDisplay = {
  live: ["vnc"],
  config: ["vnc"],
  clipboard: true,
  clipboard_config: true,
  active: true,
};
let display = vncDisplay;
const posts: string[] = [];

beforeEach(() => {
  instances.length = 0;
  posts.length = 0;
  display = vncDisplay;
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
  it("lets go of the stream when out of sight for a while, and comes back", async () => {
    let seen: (entries: { isIntersecting: boolean }[]) => void = () => undefined;
    vi.stubGlobal(
      "IntersectionObserver",
      class {
        constructor(callback: typeof seen) {
          seen = callback;
        }
        observe() {}
        disconnect() {}
      },
    );
    render(<VmConsole uuid="abc" />);
    const first = await connected();
    vi.useFakeTimers();
    try {
      act(() => seen([{ isIntersecting: false }]));
      act(() => vi.advanceTimersByTime(14_000));
      expect(first.disconnected).toBe(false);
      act(() => vi.advanceTimersByTime(2_000));
      expect(first.disconnected).toBe(true);
      expect(screen.queryByText("Connexion à la console…")).toBeNull();
      act(() => seen([{ isIntersecting: true }]));
    } finally {
      vi.useRealTimers();
    }
    await waitFor(() => expect(instances).toHaveLength(2));
  });

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

  it("only offers copy and paste for a SPICE VM", async () => {
    display = {
      live: ["spice"],
      config: ["spice"],
      clipboard: false,
      clipboard_config: false,
      active: true,
    };
    render(<VmConsole uuid="abc" />);
    expect(await screen.findByText(/copier-coller entre cet ordinateur/)).toBeTruthy();
    expect(screen.queryByText(/SPICE/)).toBeNull();
    expect(screen.queryByRole("button", { name: /affichage/ })).toBeNull();
    expect(instances).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Activer le copier-coller" }));
    display = {
      live: ["spice"],
      config: ["spice", "vnc"],
      clipboard: false,
      clipboard_config: true,
      active: true,
    };
    fireEvent.click(
      screen.getAllByRole("button", { name: "Activer le copier-coller" }).at(-1) as HTMLElement,
    );
    expect(await screen.findByText(/Copier-coller configuré/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Activer le copier-coller" })).toBeNull();
    expect(posts).toEqual(["/api/vms/abc/display/clipboard"]);
  });

  it("shows no banner once copy and paste works after a restart", async () => {
    display = {
      live: ["spice", "vnc"],
      config: ["spice", "vnc"],
      clipboard: true,
      clipboard_config: true,
      active: true,
    };
    render(<VmConsole uuid="abc" />);
    await connected();
    expect(screen.queryByText(/copier-coller/i)).toBeNull();
    expect(document.querySelector(".console-banner")).toBeNull();
  });

  it("exposes key combinations once connected", async () => {
    render(
      <>
        <VmConsole uuid="abc" />
        <Probe />
      </>,
    );
    const rfb = await connected();
    const probe = screen.getByTestId("probe");
    expect(probe.dataset.ready).toBe("no");
    act(() => void rfb.dispatchEvent(new Event("connect")));
    expect(probe.dataset.ready).toBe("yes");
    fireEvent.click(screen.getByText("cad"));
    expect(rfb.cad).toBe(1);
    fireEvent.click(screen.getByText("f2"));
    expect(rfb.keys.map(([sym, , down]) => [sym, down])).toEqual([
      [0xffe3, true],
      [0xffe9, true],
      [0xffbf, true],
      [0xffbf, false],
      [0xffe9, false],
      [0xffe3, false],
    ]);
    act(() => void rfb.dispatchEvent(new Event("disconnect")));
    expect(probe.dataset.ready).toBe("no");
  });

  it("gives the keyboard back on Ctrl+Alt", async () => {
    const { container } = render(<VmConsole uuid="abc" />);
    await connected();
    const screenEl = container.querySelector(".console-screen") as HTMLElement;
    const input = document.createElement("button");
    screenEl.appendChild(input);
    input.focus();
    expect(document.activeElement).toBe(input);
    fireEvent.keyDown(input, { key: "Control", ctrlKey: true });
    fireEvent.keyDown(input, { key: "Alt", ctrlKey: true, altKey: true });
    fireEvent.keyUp(input, { key: "Alt", ctrlKey: true });
    expect(document.activeElement).not.toBe(input);
  });

  describe("boot splash", () => {
    const STARTING = "Démarrage de la machine virtuelle…";
    const advance = (ms: number) =>
      act(async () => {
        await vi.advanceTimersByTimeAsync(ms);
      });

    it("stays 1.5 s over a console that connects at once", async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      noteStart("abc");
      render(<VmConsole uuid="abc" />);
      const rfb = await connected();
      act(() => void rfb.dispatchEvent(new Event("connect")));
      expect(screen.getByText(STARTING)).toBeTruthy();
      await advance(1200);
      expect(screen.getByText(STARTING)).toBeTruthy();
      await advance(400);
      expect(screen.queryByText(STARTING)).toBeNull();
      vi.useRealTimers();
    });

    it("goes after 3 s even when the console is still connecting", async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      noteStart("abc");
      render(<VmConsole uuid="abc" />);
      await connected();
      await advance(2500);
      expect(screen.getByText(STARTING)).toBeTruthy();
      await advance(600);
      expect(screen.queryByText(STARTING)).toBeNull();
      expect(screen.getByText("Connexion à la console…")).toBeTruthy();
      vi.useRealTimers();
    });

    it("goes at the first key, which still reaches the guest", async () => {
      noteStart("abc");
      const { container } = render(<VmConsole uuid="abc" />);
      const rfb = await connected();
      act(() => void rfb.dispatchEvent(new Event("connect")));
      const screenEl = container.querySelector(".console-screen");
      if (!screenEl) throw new Error("no console screen");
      const key = new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true });
      act(() => void screenEl.dispatchEvent(key));
      expect(key.defaultPrevented).toBe(false);
      expect(screen.queryByText(STARTING)).toBeNull();
    });

    it("goes at the first click, and lets it through", async () => {
      noteStart("abc");
      const { container } = render(<VmConsole uuid="abc" />);
      await connected();
      // The still picture when animations are reduced.
      const still = '.console-splash source[media="(prefers-reduced-motion: reduce)"]';
      expect(container.querySelector(still)).toBeTruthy();
      fireEvent.pointerDown(container.querySelector(".console-screen") as Element);
      expect(screen.queryByText(STARTING)).toBeNull();
    });

    it("is not shown for a VM that was already running", async () => {
      render(<VmConsole uuid="abc" />);
      await connected();
      expect(screen.queryByText(STARTING)).toBeNull();
      expect(screen.getByText("Connexion à la console…")).toBeTruthy();
    });

    it("is shown once per start", async () => {
      noteStart("abc");
      const first = render(<VmConsole uuid="abc" />);
      await connected();
      expect(screen.getByText(STARTING)).toBeTruthy();
      first.unmount();
      render(<VmConsole uuid="abc" />);
      await waitFor(() => expect(instances.length).toBeGreaterThan(1));
      expect(screen.queryByText(STARTING)).toBeNull();
    });
  });
});
