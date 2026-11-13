/** Menus described as data, rendered by MenuEntries for the menu bar and for context menus. */
export type MenuEntry =
  | { kind: "item"; label: string; keys?: string[]; onSelect?: () => void }
  | { kind: "sub"; label: string; entries?: MenuEntry[] }
  | {
      kind: "check";
      label: string;
      checked: boolean;
      onChange: () => void;
      keepOpen?: boolean;
      disabled?: boolean;
    }
  | { kind: "sep" };

/** An item without onSelect is greyed out. */
export const item = (label: string, keys?: string[], onSelect?: () => void): MenuEntry => ({
  kind: "item",
  label,
  keys,
  onSelect,
});
/** A submenu without entries is greyed out. */
export const sub = (label: string, entries?: MenuEntry[]): MenuEntry => ({
  kind: "sub",
  label,
  entries,
});
export const sep: MenuEntry = { kind: "sep" };
