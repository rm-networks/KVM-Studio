// X11 keysyms and DOM codes noVNC sends to QEMU for key combinations (F-62).

export interface Key {
  keysym: number;
  code: string;
}

export const KEYS = {
  ctrl: { keysym: 0xffe3, code: "ControlLeft" },
  alt: { keysym: 0xffe9, code: "AltLeft" },
  del: { keysym: 0xffff, code: "Delete" },
  backspace: { keysym: 0xff08, code: "Backspace" },
  print: { keysym: 0xff61, code: "PrintScreen" },
} satisfies Record<string, Key>;

export function functionKey(n: number): Key {
  return { keysym: 0xffbe + n - 1, code: `F${n}` };
}

export interface Combo {
  id: string;
  label: string;
  keys: Key[];
}

/** Combinations the host would keep for itself: sent to the guest from the menu. */
export const COMBOS: Combo[] = [
  ...Array.from({ length: 12 }, (_v, i) => ({
    id: `ctrl-alt-f${i + 1}`,
    label: `Ctrl+Alt+F${i + 1}`,
    keys: [KEYS.ctrl, KEYS.alt, functionKey(i + 1)],
  })),
  {
    id: "ctrl-alt-backspace",
    label: "Ctrl+Alt+Backspace",
    keys: [KEYS.ctrl, KEYS.alt, KEYS.backspace],
  },
  { id: "print", label: "PrintScreen", keys: [KEYS.print] },
];

/** Press the keys in order, release them in reverse order. */
export function pressCombo(
  send: (keysym: number, code: string, down: boolean) => void,
  keys: Key[],
): void {
  for (const k of keys) send(k.keysym, k.code, true);
  for (const k of [...keys].reverse()) send(k.keysym, k.code, false);
}
