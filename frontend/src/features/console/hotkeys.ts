import { createContext, useContext } from "react";
import type { TFunction } from "i18next";

import type { Key } from "./keys";

/** A key combination sent to the guest: modifiers first, then at most one key. */
export interface Hotkey {
  /** Empty: the keys are shown instead. */
  name: string;
  keys: string[];
}

export const MODIFIERS = ["Ctrl", "Alt", "Shift", "Win"] as const;

/*
 * X11 keysym and DOM code of each key. noVNC sends both and QEMU types the
 * physical key of the code: letters are the keys at their place on a US
 * keyboard, so a guest with another layout reads them through its own layout
 * (Win+R, Win+L and Win+D sit at the same place on AZERTY, QWERTZ and Spanish
 * keyboards; A, Q, Z, W and M do not on AZERTY).
 */
const NAMED: Record<string, Key> = {
  Ctrl: { keysym: 0xffe3, code: "ControlLeft" },
  Alt: { keysym: 0xffe9, code: "AltLeft" },
  Shift: { keysym: 0xffe1, code: "ShiftLeft" },
  Win: { keysym: 0xffeb, code: "MetaLeft" },
  Delete: { keysym: 0xffff, code: "Delete" },
  Escape: { keysym: 0xff1b, code: "Escape" },
  Tab: { keysym: 0xff09, code: "Tab" },
  Enter: { keysym: 0xff0d, code: "Enter" },
  Backspace: { keysym: 0xff08, code: "Backspace" },
  Space: { keysym: 0x0020, code: "Space" },
  PrintScreen: { keysym: 0xff61, code: "PrintScreen" },
  Insert: { keysym: 0xff63, code: "Insert" },
  Home: { keysym: 0xff50, code: "Home" },
  End: { keysym: 0xff57, code: "End" },
  PageUp: { keysym: 0xff55, code: "PageUp" },
  PageDown: { keysym: 0xff56, code: "PageDown" },
  Up: { keysym: 0xff52, code: "ArrowUp" },
  Down: { keysym: 0xff54, code: "ArrowDown" },
  Left: { keysym: 0xff51, code: "ArrowLeft" },
  Right: { keysym: 0xff53, code: "ArrowRight" },
  Pause: { keysym: 0xff13, code: "Pause" },
};

const LETTERS = Array.from({ length: 26 }, (_v, i) => String.fromCharCode(65 + i));
const DIGITS = Array.from({ length: 10 }, (_v, i) => String(i));
const FUNCTION_KEYS = Array.from({ length: 12 }, (_v, i) => `F${i + 1}`);

/** Keys a combination can end with, in the order the editor lists them. */
export const FINAL_KEYS: string[] = [
  ...LETTERS,
  ...DIGITS,
  ...FUNCTION_KEYS,
  ...Object.keys(NAMED).filter((k) => !(MODIFIERS as readonly string[]).includes(k)),
];

export function keyOf(name: string): Key | null {
  if (Object.hasOwn(NAMED, name)) return NAMED[name] ?? null;
  if (LETTERS.includes(name))
    return { keysym: name.toLowerCase().charCodeAt(0), code: `Key${name}` };
  if (DIGITS.includes(name)) return { keysym: name.charCodeAt(0), code: `Digit${name}` };
  const f = FUNCTION_KEYS.indexOf(name);
  if (f >= 0) return { keysym: 0xffbe + f, code: name };
  return null;
}

export function hotkeyKeys(hotkey: Hotkey): Key[] {
  return hotkey.keys.map(keyOf).filter((k): k is Key => k !== null);
}

const combo = (...keys: string[]): Hotkey => ({ name: "", keys });

/** The list a new user starts with, and the one a LAN guest always uses. */
export const DEFAULT_HOTKEYS: Hotkey[] = [
  combo("Ctrl", "Alt", "Delete"),
  combo("Ctrl", "Shift", "Escape"),
  combo("Win"),
  combo("Win", "R"),
  combo("Win", "L"),
  combo("Win", "D"),
  combo("Alt", "Tab"),
  combo("Alt", "F4"),
  ...Array.from({ length: 7 }, (_v, i) => combo("Ctrl", "Alt", `F${i + 1}`)),
  combo("PrintScreen"),
];

export function formatKeys(keys: string[], t: TFunction): string {
  return keys.map((k) => t(`keys.${k}`, { defaultValue: k })).join("+");
}

export function hotkeyLabel(hotkey: Hotkey, t: TFunction): string {
  return hotkey.name.trim() || formatKeys(hotkey.keys, t);
}

export const HotkeysContext = createContext<Hotkey[]>(DEFAULT_HOTKEYS);

export function useHotkeys(): Hotkey[] {
  return useContext(HotkeysContext);
}
