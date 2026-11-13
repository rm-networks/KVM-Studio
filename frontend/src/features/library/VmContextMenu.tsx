import * as ContextMenu from "@radix-ui/react-context-menu";
import type { ReactNode } from "react";

import type { VmSummary } from "../../api/client";
import { MenuEntries } from "../../components/MenuEntries";
import { useCdroms } from "../vm/useCdroms";
import { useUsb } from "../vm/useUsb";
import { useVmMenu } from "../vm/vmMenu";

interface Props {
  vm: VmSummary;
  children: ReactNode;
}

/** Mounted only while the menu is open: drives and USB devices are read then. */
function VmMenuContent({ vm }: { vm: VmSummary }) {
  const { drives } = useCdroms(vm);
  const { devices } = useUsb(vm);
  return <MenuEntries entries={useVmMenu(vm, drives, devices)} kind="context" />;
}

/** Right click on a VM of the library: the VM menu of the menu bar, for this VM. */
export function VmContextMenu({ vm, children }: Props) {
  return (
    <ContextMenu.Root>
      <ContextMenu.Trigger asChild>{children}</ContextMenu.Trigger>
      <ContextMenu.Portal>
        <ContextMenu.Content className="menu">
          <VmMenuContent vm={vm} />
        </ContextMenu.Content>
      </ContextMenu.Portal>
    </ContextMenu.Root>
  );
}
