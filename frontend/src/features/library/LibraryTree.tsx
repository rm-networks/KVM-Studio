import * as ContextMenu from "@radix-ui/react-context-menu";
import {
  ChevronDown,
  ChevronRight,
  Folder,
  FolderOpen,
  Monitor,
  MonitorSmartphone,
  TriangleAlert,
} from "lucide-react";
import { type DragEvent, type KeyboardEvent, type ReactNode, useState } from "react";
import { useTranslation } from "react-i18next";

import type { VmSummary } from "../../api/client";
import { useLibraryActions } from "./libraryActionsContext";
import { StateDot } from "./StateDot";
import { type FolderNode, folderId, parentOf, ROOT_ID, visibleRows, vmId } from "./tree";
import { VmContextMenu } from "./VmContextMenu";

const DRAG_TYPE = "application/x-kvmstudio-vm";

interface Props {
  root: FolderNode;
  selected: string | null;
  onSelect: (id: string) => void;
  onOpen: (uuid: string) => void;
  /** While searching, every folder is shown open. */
  forceOpen: boolean;
  emptyLabel?: string;
  vmsByUuid: ReadonlyMap<string, VmSummary>;
}

function MenuItem({
  label,
  onSelect,
  disabled,
}: {
  label: string;
  onSelect: () => void;
  disabled?: boolean;
}) {
  return (
    <ContextMenu.Item className="menu-item" disabled={disabled} onSelect={onSelect}>
      <span className="menu-indicator" />
      <span className="menu-label">{label}</span>
    </ContextMenu.Item>
  );
}

function FolderMenu({ path, children }: { path: string; children: ReactNode }) {
  const { t } = useTranslation();
  const actions = useLibraryActions();
  return (
    <ContextMenu.Root>
      <ContextMenu.Trigger asChild>{children}</ContextMenu.Trigger>
      <ContextMenu.Portal>
        <ContextMenu.Content className="menu">
          <MenuItem
            label={t("library.newFolder")}
            disabled={!actions.available}
            onSelect={() => actions.newFolder(path)}
          />
          {path !== "" && (
            <>
              <MenuItem label={t("menu.rename")} onSelect={() => actions.renameFolder(path)} />
              <ContextMenu.Separator className="menu-separator" />
              <MenuItem
                label={t("library.deleteFolder")}
                onSelect={() => actions.deleteFolder(path)}
              />
            </>
          )}
        </ContextMenu.Content>
      </ContextMenu.Portal>
    </ContextMenu.Root>
  );
}

export function LibraryTree({
  root,
  selected,
  onSelect,
  onOpen,
  forceOpen,
  emptyLabel,
  vmsByUuid,
}: Props) {
  const { t } = useTranslation();
  const actions = useLibraryActions();
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set([""]));
  const [dropTarget, setDropTarget] = useState<string | null>(null);

  const rows = visibleRows(root, expanded, forceOpen);
  const ids = rows.map((r) => r.id);
  const current = selected && ids.includes(selected) ? selected : ROOT_ID;
  const isOpen = (path: string) => forceOpen || expanded.has(path);

  const toggle = (path: string, open?: boolean) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (open ?? !next.has(path)) next.add(path);
      else next.delete(path);
      return next;
    });

  const onKeyDown = (e: KeyboardEvent) => {
    const index = ids.indexOf(current);
    const row = rows[index];
    const move = (i: number) => {
      const id = ids[Math.max(0, Math.min(ids.length - 1, i))];
      if (id) onSelect(id);
    };
    switch (e.key) {
      case "ArrowDown":
        move(index + 1);
        break;
      case "ArrowUp":
        move(index - 1);
        break;
      case "Home":
        move(0);
        break;
      case "End":
        move(ids.length - 1);
        break;
      case "ArrowRight":
        if (row?.folder) {
          if (isOpen(row.folder.path)) move(index + 1);
          else toggle(row.folder.path, true);
        }
        break;
      case "ArrowLeft":
        if (row?.folder && isOpen(row.folder.path) && !forceOpen) {
          toggle(row.folder.path, false);
        } else if (row && !(row.folder?.path === "")) {
          const parent = row.vm ? row.vm.folder : parentOf(row.folder?.path ?? "");
          onSelect(folderId(parent));
        }
        break;
      case "Enter":
        if (row?.vm) onOpen(row.vm.uuid);
        else if (row?.folder) toggle(row.folder.path);
        break;
      case "F2":
        if (row?.folder && row.folder.path !== "") actions.renameFolder(row.folder.path);
        break;
      default:
        return;
    }
    e.preventDefault();
  };

  const dropProps = (path: string) => ({
    onDragOver: (e: DragEvent) => {
      if (!e.dataTransfer.types.includes(DRAG_TYPE)) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      setDropTarget(path);
    },
    onDragLeave: () => setDropTarget((p) => (p === path ? null : p)),
    onDrop: (e: DragEvent) => {
      e.preventDefault();
      setDropTarget(null);
      const vm = vmsByUuid.get(e.dataTransfer.getData(DRAG_TYPE));
      if (vm) actions.moveVm(vm, path);
    },
  });

  return (
    <ul
      className="tree"
      role="tree"
      tabIndex={0}
      aria-label={t("library.title")}
      aria-activedescendant={`tree-${current}`}
      onKeyDown={onKeyDown}
    >
      {rows.map((row) => {
        const isSelected = current === row.id;
        if (row.folder) {
          const folder = row.folder;
          const open = isOpen(folder.path);
          const isRoot = folder.path === "";
          const classes = ["tree-row"];
          if (isSelected) classes.push("selected");
          if (dropTarget === folder.path) classes.push("drop-target");
          return (
            <li
              key={row.id}
              id={`tree-${row.id}`}
              role="treeitem"
              aria-level={row.depth + 1}
              aria-expanded={open}
              aria-selected={isSelected}
            >
              <FolderMenu path={folder.path}>
                <div
                  className={classes.join(" ")}
                  style={{ paddingLeft: 4 + row.depth * 16 }}
                  onClick={() => onSelect(row.id)}
                  onContextMenu={() => onSelect(row.id)}
                  onDoubleClick={() => toggle(folder.path)}
                  {...(actions.available ? dropProps(folder.path) : {})}
                >
                  <span
                    className="tree-twisty"
                    onClick={(e) => {
                      e.stopPropagation();
                      toggle(folder.path);
                    }}
                  >
                    {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                  </span>
                  {isRoot ? (
                    <MonitorSmartphone size={14} strokeWidth={1.75} className="tree-icon" />
                  ) : open ? (
                    <FolderOpen size={14} strokeWidth={1.75} className="tree-icon" />
                  ) : (
                    <Folder size={14} strokeWidth={1.75} className="tree-icon" />
                  )}
                  <span className="tree-label">
                    {isRoot ? t("library.myComputer") : folder.name}
                  </span>
                </div>
              </FolderMenu>
              {isRoot && open && rows.length === 1 && (
                <div className="tree-empty">{emptyLabel ?? t("library.empty")}</div>
              )}
            </li>
          );
        }
        const vm = row.vm as VmSummary;
        const drift = vm.drift.map((d) => t(`library.drift.${d}`)).join(" ");
        return (
          <li
            key={row.id}
            id={`tree-${row.id}`}
            role="treeitem"
            aria-level={row.depth + 1}
            aria-selected={isSelected}
          >
            <VmContextMenu vm={vm} onOpen={onOpen}>
              <div
                className={isSelected ? "tree-row selected" : "tree-row"}
                style={{ paddingLeft: 22 + row.depth * 16 }}
                title={`${vm.name} (${t(`state.${vm.state}`)})${drift ? `\n${drift}` : ""}`}
                draggable={actions.available}
                onDragStart={(e) => {
                  e.dataTransfer.setData(DRAG_TYPE, vm.uuid);
                  e.dataTransfer.effectAllowed = "move";
                }}
                onClick={() => onSelect(vmId(vm.uuid))}
                onContextMenu={() => onSelect(vmId(vm.uuid))}
                onDoubleClick={() => onOpen(vm.uuid)}
              >
                <span className="tree-icon tree-vm-icon">
                  <Monitor size={14} strokeWidth={1.75} />
                  <StateDot state={vm.state} />
                </span>
                <span className="tree-label">{vm.name}</span>
                {vm.drift.length > 0 && (
                  <TriangleAlert size={12} className="tree-drift" role="img" aria-label={drift} />
                )}
              </div>
            </VmContextMenu>
          </li>
        );
      })}
    </ul>
  );
}
