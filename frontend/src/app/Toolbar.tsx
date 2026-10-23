import {
  Camera,
  ChevronDown,
  History,
  Keyboard,
  LayoutGrid,
  type LucideIcon,
  Maximize,
  PanelLeft,
  Play,
  RotateCcw,
  SquareTerminal,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import "./Toolbar.css";

interface Props {
  libraryVisible: boolean;
  onToggleLibrary: () => void;
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
      className={narrow ? "tool tool-narrow" : "tool"}
      title={label}
      aria-label={label}
      aria-pressed={pressed}
      disabled={!onClick}
      onClick={onClick}
    >
      <Icon size={narrow ? 12 : 16} strokeWidth={1.75} />
    </button>
  );
}

export function Toolbar({ libraryVisible, onToggleLibrary }: Props) {
  const { t } = useTranslation();
  const l = (key: string) => t(`toolbar.${key}`);

  return (
    <div className="toolbar" role="toolbar">
      <Tool icon={Play} label={l("start")} />
      <Tool icon={ChevronDown} label={l("powerMenu")} narrow />
      <span className="toolbar-separator" />
      <Tool icon={Keyboard} label={l("sendCad")} />
      <span className="toolbar-separator" />
      <Tool icon={Camera} label={l("snapshot")} />
      <Tool icon={RotateCcw} label={l("revert")} />
      <Tool icon={History} label={l("snapshotManager")} />
      <span className="toolbar-separator" />
      <Tool
        icon={PanelLeft}
        label={l("library")}
        pressed={libraryVisible}
        onClick={onToggleLibrary}
      />
      <Tool icon={LayoutGrid} label={l("thumbnails")} />
      <Tool icon={Maximize} label={l("fullscreen")} />
      <span className="toolbar-separator" />
      <Tool icon={SquareTerminal} label={l("console")} />
    </div>
  );
}
