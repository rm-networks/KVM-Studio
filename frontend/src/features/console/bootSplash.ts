import { useEffect, useState } from "react";

// The firmware logo shows while the console connects: the splash covers it,
// without ever hiding a "press any key" prompt or a boot menu for long.
export const SPLASH_MIN_MS = 1500;
export const SPLASH_MAX_MS = 3000;
// A console opened later than this after the start is a VM already running.
const FRESH_MS = 5000;

const starts = new Map<string, number>();

/** The user started this VM from the application. */
export function noteStart(uuid: string): void {
  starts.set(uuid, Date.now());
}

export function cancelStart(uuid: string): void {
  starts.delete(uuid);
}

function justStarted(uuid: string): boolean {
  const at = starts.get(uuid);
  return at !== undefined && Date.now() - at < FRESH_MS;
}

/**
 * Whether the console shows the splash: from 1.5 s (or until connected, if
 * later) to 3 s at most, gone at the first key or click, which still reach
 * the guest.
 */
export function useBootSplash(uuid: string, connected: boolean): boolean {
  const [shown, setShown] = useState(() => justStarted(uuid));
  const [minDone, setMinDone] = useState(false);

  useEffect(() => {
    if (!shown) return;
    starts.delete(uuid);
    const hide = () => setShown(false);
    const min = window.setTimeout(() => setMinDone(true), SPLASH_MIN_MS);
    const max = window.setTimeout(hide, SPLASH_MAX_MS);
    window.addEventListener("keydown", hide, { capture: true });
    window.addEventListener("pointerdown", hide, { capture: true });
    return () => {
      window.clearTimeout(min);
      window.clearTimeout(max);
      window.removeEventListener("keydown", hide, { capture: true });
      window.removeEventListener("pointerdown", hide, { capture: true });
    };
  }, [shown, uuid]);

  return shown && !(minDone && connected);
}
