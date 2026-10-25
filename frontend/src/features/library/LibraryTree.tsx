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
import { type DragEvent, type KeyboardEvent, type ReactNode, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { VmSummary } from "../../api/client";
import { useLibraryActions } from "./libraryActionsContext";
import { StateDot } from "./StateDot";
import { type FolderNode, folderId, parentOf, ROOT_ID, visibleRows, vmId } from "./tree";
import { VmContextMenu } from "./VmContextMenu";

const DRAG_TYPE = "application/x-kvmstudio-vm";
const FOLDER_TYPE = "application/x-kvmstudio-folder";

type DropWhere = "into" | "before" | "after";

function findFolder(node: FolderNode, path: string): FolderNode | null {
  if (node.path === path) return node;
  for (const child of node.folders) {
    if (path === child.path || path.startsWith(`${child.path}/`)) return findFolder(child, path);
  }
  return null;
}

const inside = (path: string, top: string) => path === top || path.startsWith(`${top}/`);

interface Props {
  root: FolderNode;
  selected: string | null;
  onSelect: (id: string) => void;
  onOpen: (uuid: string) => void;
  onSettings: (uuid: string) => void;
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
  onSettings,
  forceOpen,
  emptyLabel,
  vmsByUuid,
}: Props) {
  const { t } = useTranslation();
  const actions = useLibraryActions();
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set([""]));
  const [dropTarget, setDropTarget] = useState<{ path: string; where: DropWhere } | null>(null);
  // The folder being dragged: its path cannot be read from the event before the drop.
  const draggedFolder = useRef<string | null>(null);

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

  // A folder dropped on the top or bottom edge of another goes next to it,
  // anywhere else into it.
  const whereFor = (e: DragEvent, path: string, dragged: string | null): DropWhere | null => {
    if (dragged === null) return null;
    let where: DropWhere = "into";
    if (path !== "") {
      const box = e.currentTarget.getBoundingClientRect();
      const y = (e.clientY - box.top) / Math.max(box.height, 1);
      if (y < 0.25) where = "before";
      else if (y > 0.75) where = "after";
    }
    const parent = where === "into" ? path : parentOf(path);
    if (inside(parent, dragged) || (where !== "into" && path === dragged)) return null;
    return where;
  };

  const dropFolder = (dragged: string, path: string, where: DropWhere) => {
    if (where === "into") {
      actions.moveFolder(dragged, path, null);
      return;
    }
    const parent = parentOf(path);
    const siblings = (findFolder(root, parent)?.folders ?? []).filter((f) => f.path !== dragged);
    const index = siblings.findIndex((f) => f.path === path);
    const next = where === "before" ? siblings[index] : siblings[index + 1];
    actions.moveFolder(dragged, parent, next?.name ?? null);
  };

  const dropProps = (path: string) => ({
    onDragOver: (e: DragEvent) => {
      let where: DropWhere | null = null;
      if (e.dataTransfer.types.includes(DRAG_TYPE)) where = "into";
      else if (e.dataTransfer.types.includes(FOLDER_TYPE))
        where = whereFor(e, path, draggedFolder.current);
      if (!where) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      setDropTarget({ path, where });
    },
    onDragLeave: () => setDropTarget((d) => (d?.path === path ? null : d)),
    onDrop: (e: DragEvent) => {
      e.preventDefault();
      setDropTarget(null);
      const dragged = draggedFolder.current;
      draggedFolder.current = null;
      if (e.dataTransfer.types.includes(FOLDER_TYPE) && dragged !== null) {
        const where = whereFor(e, path, dragged);
        if (where) dropFolder(dragged, path, where);
        return;
      }
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
          if (dropTarget?.path === folder.path) {
            classes.push(dropTarget.where === "into" ? "drop-target" : `drop-${dropTarget.where}`);
          }
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
                  draggable={actions.available && !isRoot && !forceOpen}
                  onDragStart={(e) => {
                    draggedFolder.current = folder.path;
                    e.dataTransfer.setData(FOLDER_TYPE, folder.path);
                    e.dataTransfer.effectAllowed = "move";
                  }}
                  onDragEnd={() => {
                    draggedFolder.current = null;
                    setDropTarget(null);
                  }}
                  {...(actions.available ? dropProps(folder.path) : {})}
                >
                  <span
                    className="tree-twisty"
                    onClick={(e) => {
                      e.stopPropagation();
                      toggle(folder.path);
                    }}
                  >
                    {open ? <ChevronDown /> : <ChevronRight />}
                  </span>
                  {isRoot ? (
                    <MonitorSmartphone className="tree-icon" />
                  ) : open ? (
                    <FolderOpen className="tree-icon" />
                  ) : (
                    <Folder className="tree-icon" />
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
            <VmContextMenu vm={vm} onOpen={onOpen} onSettings={onSettings}>
              <div
                className={isSelected ? "tree-row selected" : "tree-row"}
                style={{ paddingLeft: 22 + row.depth * 16 }}
                title={`${vm.name} (${t(`state.${vm.state}`)})${drift ? `\n${drift}` : ""}`}
                draggable={actions.available}
                onDragStart={(e) => {
                  e.dataTransfer.setData(DRAG_TYPE, vm.uuid);
                  e.dataTransfer.effectAllowed = "move";
                }}
                onClick={() => {
                  // Like Workstation: one click shows the VM's tab, opening it if needed.
                  onSelect(vmId(vm.uuid));
                  onOpen(vm.uuid);
                }}
                onContextMenu={() => onSelect(vmId(vm.uuid))}
              >
                <span className="tree-icon tree-vm-icon">
                  <Monitor />
                  <StateDot state={vm.state} />
                </span>
                <span className="tree-label">{vm.name}</span>
                {vm.drift.length > 0 && (
                  <TriangleAlert className="tree-drift" role="img" aria-label={drift} />
                )}
              </div>
            </VmContextMenu>
          </li>
        );
      })}
    </ul>
  );
}
