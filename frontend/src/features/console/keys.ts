// A key as noVNC sends it to QEMU: X11 keysym and DOM code (F-62).

export interface Key {
  keysym: number;
  code: string;
}

/** Press the keys in order, release them in reverse order. */
export function pressCombo(
  send: (keysym: number, code: string, down: boolean) => void,
  keys: Key[],
): void {
  for (const k of keys) send(k.keysym, k.code, true);
  for (const k of [...keys].reverse()) send(k.keysym, k.code, false);
}
