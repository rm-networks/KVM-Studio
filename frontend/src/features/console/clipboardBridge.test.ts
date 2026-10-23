import { describe, expect, it } from "vitest";

import type { HostClipboard } from "../../platform/hostClipboard";
import { ClipboardBridge } from "./clipboardBridge";

function setup(initial: string | null = null) {
  const host = { text: initial };
  const clipboard: HostClipboard = {
    read: () => Promise.resolve(host.text),
    write: (text) => {
      host.text = text;
      return Promise.resolve();
    },
  };
  const sent: string[] = [];
  const bridge = new ClipboardBridge({ clipboardPasteFrom: (t) => sent.push(t) }, clipboard);
  return { host, sent, bridge };
}

describe("ClipboardBridge", () => {
  it("offers new host text to the guest once", async () => {
    const { sent, bridge } = setup("Crème brûlée à 4 €");
    expect(await bridge.toGuest()).toBe(true);
    expect(await bridge.toGuest()).toBe(false);
    expect(sent).toEqual(["Crème brûlée à 4 €"]);
  });

  it("copies guest text to the host without echoing it back", async () => {
    const { host, sent, bridge } = setup("old");
    await bridge.fromGuest("Œuvre naïve");
    expect(host.text).toBe("Œuvre naïve");
    expect(await bridge.toGuest()).toBe(false);
    expect(sent).toEqual([]);
  });

  it("ignores an empty or unreadable host clipboard", async () => {
    expect(await setup(null).bridge.toGuest()).toBe(false);
    expect(await setup("").bridge.toGuest()).toBe(false);
  });
});
