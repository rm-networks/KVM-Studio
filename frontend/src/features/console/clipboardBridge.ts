import type { HostClipboard } from "../../platform/hostClipboard";

interface PasteTarget {
  clipboardPasteFrom(text: string): void;
}

/**
 * Keeps host and guest clipboards in step without echoing a text back to where
 * it came from. Text only, as in the specification.
 */
export class ClipboardBridge {
  private lastShared: string | null = null;

  constructor(
    private readonly guest: PasteTarget,
    private readonly host: HostClipboard,
  ) {}

  /** The guest copied something: put it on the host clipboard. */
  async fromGuest(text: string): Promise<void> {
    this.lastShared = text;
    await this.host.write(text);
  }

  /** Offer the host clipboard to the guest if it changed. Returns true if sent. */
  async toGuest(): Promise<boolean> {
    const text = await this.host.read();
    if (!text || text === this.lastShared) return false;
    this.lastShared = text;
    this.guest.clipboardPasteFrom(text);
    return true;
  }
}
