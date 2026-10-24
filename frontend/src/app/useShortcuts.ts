import { useEffect, useRef } from "react";

export interface ShortcutActions {
  newVm: () => void;
  closeTab: () => void;
  nextTab: () => void;
  previousTab: () => void;
  preferences: () => void;
  grab: () => void;
  fullscreen: () => void;
}

/** Workstation shortcuts. Keys typed in a console or a text field are left alone. */
export function useShortcuts(actions: ShortcutActions): void {
  const latest = useRef(actions);
  useEffect(() => {
    latest.current = actions;
  });

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      const a = latest.current;
      const target = e.target instanceof Element ? e.target : null;
      if (e.ctrlKey && e.altKey && e.key === "Enter") {
        e.preventDefault();
        a.fullscreen();
        return;
      }
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
            : { n: a.newVm, w: a.closeTab, p: a.preferences, g: a.grab }[key];
      if (handler) {
        e.preventDefault();
        handler();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);
}
