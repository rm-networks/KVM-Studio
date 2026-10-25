interface FullscreenApi {
  toggle_fullscreen?: () => Promise<void>;
  set_fullscreen?: (on: boolean) => Promise<boolean>;
}

interface KeyboardLock {
  lock?: (keys?: string[]) => Promise<void>;
  unlock?: () => void;
}

function desktopApi(): FullscreenApi | undefined {
  return window.pywebview?.api as FullscreenApi | undefined;
}

/** Full screen for the whole window: pywebview in the desktop window, the Fullscreen API in a browser. */
export function toggleFullscreen(): void {
  const api = desktopApi();
  if (api?.toggle_fullscreen) {
    void api.toggle_fullscreen();
    return;
  }
  if (document.fullscreenElement) void document.exitFullscreen();
  else void document.documentElement.requestFullscreen?.();
}

/** True in a browser, where Escape leaving full screen is imposed by the browser. */
export function browserFullscreen(): boolean {
  return !desktopApi()?.set_fullscreen;
}

/**
 * Window full screen on or off for the VM console. Returns whether it was on
 * before, so that leaving the console full screen puts the window back as it was.
 * In a browser, the keyboard is locked when the browser allows it (Chromium):
 * Escape and the system shortcuts then reach the VM.
 */
export async function setFullscreen(on: boolean): Promise<boolean> {
  const api = desktopApi();
  if (api?.set_fullscreen) return api.set_fullscreen(on);
  const before = document.fullscreenElement !== null;
  const keyboard = (navigator as Navigator & { keyboard?: KeyboardLock }).keyboard;
  try {
    if (on && !before) {
      await document.documentElement.requestFullscreen?.();
      await keyboard?.lock?.();
    } else if (!on && before) {
      keyboard?.unlock?.();
      await document.exitFullscreen();
    }
  } catch {
    // Refused (no user gesture, not allowed): the console still fills the page.
  }
  return before;
}

/** Whether the browser keeps Escape for the page in full screen (Keyboard Lock API). */
export function keyboardLockAvailable(): boolean {
  return (
    typeof (navigator as Navigator & { keyboard?: KeyboardLock }).keyboard?.lock === "function"
  );
}
