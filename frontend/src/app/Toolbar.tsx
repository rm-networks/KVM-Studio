import { ChevronDown, Keyboard, type LucideIcon, Maximize, PanelLeft, Play } from "lucide-react";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { useTranslation } from "react-i18next";

import type { VmSummary } from "../api/client";
import type { ConsoleHandle } from "../features/console/consoleRegistry";
import { POWER_ACTIONS, powerAllowed } from "../features/vm/power";
import { useVmActions } from "../features/vm/vmActionsContext";

import "./Toolbar.css";

interface Props {
  libraryVisible: boolean;
  onToggleLibrary: () => void;
  vm: VmSummary | null;
  vmConsole: ConsoleHandle | null;
  onFullscreen: () => void;
}

interface ToolProps {
  icon: LucideIcon;
  label: string;
  onClick?: () => void;
  pressed?: boolean;
  narrow?: boolean;
}

function Tool({ icon: Icon, label, onClick, pressed, narrow }: ToolProps) {
  return (
    <button
      type="button"
      className={narrow ? "icon-button tool-narrow" : "icon-button"}
      title={label}
      aria-label={label}
      aria-pressed={pressed}
      disabled={!onClick}
      onClick={onClick}
    >
      <Icon />
    </button>
  );
}

export function Toolbar({ libraryVisible, onToggleLibrary, vm, vmConsole, onFullscreen }: Props) {
  const { t } = useTranslation();
  const actions = useVmActions();
  const l = (key: string) => t(`toolbar.${key}`);
  const canStart = vm !== null && powerAllowed(vm.state, "start");

  return (
    <div className="toolbar" role="toolbar">
      <Tool
        icon={Play}
        label={l("start")}
        onClick={canStart && vm ? () => actions.power(vm, "start") : undefined}
      />
      <DropdownMenu.Root>
        <DropdownMenu.Trigger
          className="icon-button tool-narrow"
          title={l("powerMenu")}
          aria-label={l("powerMenu")}
          disabled={!vm}
        >
          <ChevronDown />
        </DropdownMenu.Trigger>
        <DropdownMenu.Portal>
          <DropdownMenu.Content className="menu" align="start" sideOffset={2}>
            {POWER_ACTIONS.map((action) => (
              <DropdownMenu.Item
                key={action}
                className="menu-item"
                disabled={!vm || !powerAllowed(vm.state, action)}
                onSelect={() => vm && actions.power(vm, action)}
              >
                <span className="menu-indicator" />
                <span className="menu-label">{t(`power.${action}`)}</span>
              </DropdownMenu.Item>
            ))}
          </DropdownMenu.Content>
        </DropdownMenu.Portal>
      </DropdownMenu.Root>
      <span className="toolbar-separator" />
      <Tool
        icon={Keyboard}
        label={l("sendCad")}
        onClick={vmConsole ? () => vmConsole.sendCtrlAltDel() : undefined}
      />
      <span className="toolbar-separator" />
      <Tool
        icon={PanelLeft}
        label={l("library")}
        pressed={libraryVisible}
        onClick={onToggleLibrary}
      />
      <Tool icon={Maximize} label={l("fullscreen")} onClick={onFullscreen} />
    </div>
  );
}
