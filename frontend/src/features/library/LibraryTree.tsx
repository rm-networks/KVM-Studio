import { ChevronDown, ChevronRight, Monitor, MonitorSmartphone } from "lucide-react";
import { type KeyboardEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import type { VmSummary } from "../../api/client";
import { VmContextMenu } from "./VmContextMenu";
import { StateDot } from "./StateDot";

export const ROOT_ID = "my-computer";

interface Props {
  vms: VmSummary[];
  selected: string | null;
  onSelect: (id: string) => void;
  onOpen: (uuid: string) => void;
  /** Shown under My Computer when the list is empty. */
  emptyLabel?: string;
}

export function LibraryTree({ vms, selected, onSelect, onOpen, emptyLabel }: Props) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(true);
  const sorted = vms;

  const visible = expanded ? [ROOT_ID, ...sorted.map((vm) => vm.uuid)] : [ROOT_ID];
  const current = selected && visible.includes(selected) ? selected : ROOT_ID;

  const onKeyDown = (e: KeyboardEvent) => {
    const index = visible.indexOf(current);
    const move = (i: number) => {
      const id = visible[Math.max(0, Math.min(visible.length - 1, i))];
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
        move(visible.length - 1);
        break;
      case "ArrowRight":
        if (current === ROOT_ID) {
          if (expanded) move(1);
          else setExpanded(true);
        }
        break;
      case "ArrowLeft":
        if (current === ROOT_ID) setExpanded(false);
        else onSelect(ROOT_ID);
        break;
      case "Enter":
        if (current === ROOT_ID) setExpanded((v) => !v);
        else onOpen(current);
        break;
      default:
        return;
    }
    e.preventDefault();
  };

  return (
    <ul
      className="tree"
      role="tree"
      tabIndex={0}
      aria-label={t("library.title")}
      aria-activedescendant={`tree-${current}`}
      onKeyDown={onKeyDown}
    >
      <li
        id={`tree-${ROOT_ID}`}
        role="treeitem"
        aria-expanded={expanded}
        aria-selected={current === ROOT_ID}
      >
        <div
          className={current === ROOT_ID ? "tree-row selected" : "tree-row"}
          onClick={() => onSelect(ROOT_ID)}
          onDoubleClick={() => setExpanded((v) => !v)}
        >
          <span
            className="tree-twisty"
            onClick={(e) => {
              e.stopPropagation();
              setExpanded((v) => !v);
            }}
          >
            {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          </span>
          <MonitorSmartphone size={14} strokeWidth={1.75} className="tree-icon" />
          <span className="tree-label">{t("library.myComputer")}</span>
        </div>
        {expanded && (
          <ul role="group">
            {sorted.length === 0 && (
              <li className="tree-empty">{emptyLabel ?? t("library.empty")}</li>
            )}
            {sorted.map((vm) => (
              <li
                key={vm.uuid}
                id={`tree-${vm.uuid}`}
                role="treeitem"
                aria-selected={current === vm.uuid}
              >
                <VmContextMenu vm={vm} onOpen={onOpen}>
                  <div
                    className={
                      current === vm.uuid ? "tree-row tree-leaf selected" : "tree-row tree-leaf"
                    }
                    title={`${vm.name} (${t(`state.${vm.state}`)})`}
                    onClick={() => onSelect(vm.uuid)}
                    onContextMenu={() => onSelect(vm.uuid)}
                    onDoubleClick={() => onOpen(vm.uuid)}
                  >
                    <span className="tree-icon tree-vm-icon">
                      <Monitor size={14} strokeWidth={1.75} />
                      <StateDot state={vm.state} />
                    </span>
                    <span className="tree-label">{vm.name}</span>
                  </div>
                </VmContextMenu>
              </li>
            ))}
          </ul>
        )}
      </li>
    </ul>
  );
}
