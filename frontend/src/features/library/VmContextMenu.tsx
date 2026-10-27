import * as ContextMenu from "@radix-ui/react-context-menu";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { VmSummary } from "../../api/client";
import { POWER_ACTIONS, powerAllowed } from "../vm/power";
import { useVmActions } from "../vm/vmActionsContext";
import { useLibraryActions } from "./libraryActionsContext";

interface Props {
  vm: VmSummary;
  onOpen: (uuid: string) => void;
  onSettings: (uuid: string) => void;
  children: ReactNode;
}

function Item({
  label,
  keys,
  onSelect,
  disabled,
}: {
  label: string;
  keys?: string;
  onSelect: () => void;
  disabled?: boolean;
}) {
  return (
    <ContextMenu.Item className="menu-item" disabled={disabled} onSelect={onSelect}>
      <span className="menu-indicator" />
      <span className="menu-label">{label}</span>
      {keys && <span className="menu-keys">{keys}</span>}
    </ContextMenu.Item>
  );
}

export function VmContextMenu({ vm, onOpen, onSettings, children }: Props) {
  const { t } = useTranslation();
  const actions = useVmActions();
  const library = useLibraryActions();
  return (
    <ContextMenu.Root>
      <ContextMenu.Trigger asChild>{children}</ContextMenu.Trigger>
      <ContextMenu.Portal>
        <ContextMenu.Content className="menu">
          <Item label={t("menu.openTab")} onSelect={() => onOpen(vm.uuid)} />
          <ContextMenu.Separator className="menu-separator" />
          {POWER_ACTIONS.map((action) => (
            <Item
              key={action}
              label={t(`power.${action}`)}
              disabled={!powerAllowed(vm.state, action)}
              onSelect={() => actions.power(vm, action)}
            />
          ))}
          <ContextMenu.Separator className="menu-separator" />
          <Item label={t("menu.snapshotManager")} onSelect={() => library.snapshots(vm)} />
          <Item label={t("menu.clone")} onSelect={() => actions.clone(vm)} />
          <Item label={t("menu.rename")} onSelect={() => actions.rename(vm)} />
          <Item label={t("library.moveTo")} onSelect={() => library.moveVm(vm)} />
          {/* Only when there is something to move. */}
          {vm.files === "outside" && (
            <Item
              label={t("library.importFiles")}
              disabled={!library.available}
              onSelect={() => library.importVm(vm)}
            />
          )}
          {vm.files === "loose" && (
            <Item label={t("library.tidyFiles")} onSelect={() => library.tidyVm(vm)} />
          )}
          <Item label={t("menu.removeFromLibrary")} onSelect={() => actions.remove(vm, false)} />
          <Item label={t("menu.deleteFromDisk")} onSelect={() => actions.remove(vm, true)} />
          <ContextMenu.Separator className="menu-separator" />
          <Item label={t("menu.settings")} keys="Ctrl+D" onSelect={() => onSettings(vm.uuid)} />
        </ContextMenu.Content>
      </ContextMenu.Portal>
    </ContextMenu.Root>
  );
}
