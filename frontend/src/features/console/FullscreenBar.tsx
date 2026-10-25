import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { ChevronDown, Keyboard, Minimize, Power } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { VmSummary } from "../../api/client";
import { POWER_ACTIONS, powerAllowed } from "../vm/power";
import { useVmActions } from "../vm/vmActionsContext";
import type { ConsoleHandle } from "./consoleRegistry";
import "./FullscreenBar.css";

const BAR_HIDE_MS = 2000;
// Pixels from the top of the screen that bring the bar out.
const EDGE_PX = 2;

interface Props {
  vm: VmSummary;
  vmConsole: ConsoleHandle | null;
  onExit: () => void;
}

/**
 * Thin bar of the VM console in full screen: it comes out when the pointer
 * touches the top of the screen and hides 2 s after the pointer left it.
 */
export function FullscreenBar({ vm, vmConsole, onExit }: Props) {
  const { t } = useTranslation();
  const actions = useVmActions();
  const [shown, setShown] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const hovered = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => {
    const later = () => {
      clearTimeout(timer.current);
      timer.current = setTimeout(() => !hovered.current && setShown(false), BAR_HIDE_MS);
    };
    // Capture phase: the console canvas keeps the pointer events to itself.
    const onMove = (e: MouseEvent) => {
      if (e.clientY <= EDGE_PX) {
        setShown(true);
        later();
      }
    };
    window.addEventListener("mousemove", onMove, true);
    return () => {
      window.removeEventListener("mousemove", onMove, true);
      clearTimeout(timer.current);
    };
  }, []);

  const visible = shown || menuOpen;
  return (
    <div
      className="fullscreen-bar"
      data-visible={visible}
      role="toolbar"
      aria-label={vm.name}
      onMouseEnter={() => {
        hovered.current = true;
        clearTimeout(timer.current);
      }}
      onMouseLeave={() => {
        hovered.current = false;
        timer.current = setTimeout(() => setShown(false), BAR_HIDE_MS);
      }}
    >
      <span className="fullscreen-bar-name">{vm.name}</span>
      <DropdownMenu.Root open={menuOpen} onOpenChange={setMenuOpen}>
        <DropdownMenu.Trigger className="fullscreen-bar-button" title={t("toolbar.powerMenu")}>
          <Power aria-hidden />
          <ChevronDown aria-hidden className="fullscreen-bar-chevron" />
        </DropdownMenu.Trigger>
        <DropdownMenu.Portal>
          <DropdownMenu.Content className="menu fullscreen-bar-menu" align="center" sideOffset={2}>
            {POWER_ACTIONS.map((action) => (
              <DropdownMenu.Item
                key={action}
                className="menu-item"
                disabled={!powerAllowed(vm.state, action)}
                onSelect={() => actions.power(vm, action)}
              >
                <span className="menu-indicator" />
                <span className="menu-label">{t(`power.${action}`)}</span>
              </DropdownMenu.Item>
            ))}
          </DropdownMenu.Content>
        </DropdownMenu.Portal>
      </DropdownMenu.Root>
      <button
        type="button"
        className="fullscreen-bar-button"
        disabled={!vmConsole}
        onClick={() => vmConsole?.sendCtrlAltDel()}
      >
        <Keyboard aria-hidden />
        {t("menu.sendCad")}
      </button>
      <button type="button" className="fullscreen-bar-button" onClick={onExit}>
        <Minimize aria-hidden />
        {t("console.exitFullscreen")}
        <kbd>{t("console.fullscreenKeys")}</kbd>
      </button>
    </div>
  );
}
