import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { useTranslation } from "react-i18next";

import type { ConsoleHandle } from "./consoleRegistry";
import { hotkeyKeys, hotkeyLabel, useHotkeys } from "./hotkeys";

/** Send Key: the combinations of Preferences, Hotkeys, as dropdown items. */
export function SendKeyItems({ vmConsole }: { vmConsole: ConsoleHandle | null }) {
  const { t } = useTranslation();
  return useHotkeys().map((hotkey, i) => (
    <DropdownMenu.Item
      key={i}
      className="menu-item"
      disabled={!vmConsole}
      onSelect={() => vmConsole?.sendKeys(hotkeyKeys(hotkey))}
    >
      <span className="menu-indicator" />
      <span className="menu-label">{hotkeyLabel(hotkey, t)}</span>
    </DropdownMenu.Item>
  ));
}
