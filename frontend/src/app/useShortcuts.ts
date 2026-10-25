import { useEffect, useRef } from "react";

export interface ShortcutActions {
  newVm: () => void;
  closeTab: () => void;
  nextTab: () => void;
  previousTab: () => void;
  preferences: () => void;
  settings: () => void;
  grab: () => void;
  consoleFullscreen: () => void;
  appFullscreen: () => void;
}

/** Workstation shortcuts. Keys typed in a console or a text field are left alone. */
export function useShortcuts(actions: ShortcutActions): void {
  const latest = useRef(actions);
  useEffect(() => {
    latest.current = actions;
  });

  useEffect(() => {
    // Capture phase: Ctrl+Alt+Enter also works while the console holds the
    // keyboard (the console itself keeps it from the guest).
    const onFullscreenKey = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.altKey && e.key === "Enter") {
        e.preventDefault();
        latest.current.consoleFullscreen();
      } else if (
        e.key === "F11" &&
        !e.ctrlKey &&
        !e.altKey &&
        !e.shiftKey &&
        // A console holding the keyboard gives F11 to the guest.
        !(e.target instanceof Element && e.target.closest(".console-screen"))
      ) {
        e.preventDefault();
        latest.current.appFullscreen();
      }
    };
    const onKeyDown = (e: KeyboardEvent) => {
      const a = latest.current;
      const target = e.target instanceof Element ? e.target : null;
      if (target?.closest(".console-screen, input, textarea, select, [contenteditable='true']")) {
        return;
      }
      if (!e.ctrlKey || e.altKey || e.metaKey) return;
      const key = e.key.toLowerCase();
      const handler =
        key === "tab"
          ? e.shiftKey
            ? a.previousTab
            : a.nextTab
          : e.shiftKey
            ? undefined
            : { n: a.newVm, w: a.closeTab, p: a.preferences, g: a.grab, d: a.settings }[key];
      if (handler) {
        e.preventDefault();
        handler();
      }
    };
    window.addEventListener("keydown", onFullscreenKey, true);
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onFullscreenKey, true);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, []);
}
