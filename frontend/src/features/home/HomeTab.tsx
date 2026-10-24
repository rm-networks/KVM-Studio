import { FolderOpen, type LucideIcon, Plus, Server } from "lucide-react";
import { useTranslation } from "react-i18next";

import "./HomeTab.css";

function Tile({
  icon: Icon,
  label,
  hint,
  onClick,
}: {
  icon: LucideIcon;
  label: string;
  hint?: string;
  onClick?: () => void;
}) {
  return (
    <button type="button" className="home-tile" disabled={!onClick} title={hint} onClick={onClick}>
      <Icon size={30} strokeWidth={1.25} />
      <span>{label}</span>
    </button>
  );
}

export function HomeTab({ onNewVm }: { onNewVm: () => void }) {
  const { t } = useTranslation();
  const later = t("home.later");
  return (
    <div className="home">
      <img className="home-logo" src="/logo.png" alt="" width={96} height={96} />
      <h1 className="home-title">KVM Studio</h1>
      <div className="home-tiles">
        <Tile icon={Plus} label={t("home.create")} onClick={onNewVm} />
        <Tile icon={FolderOpen} label={t("home.open")} hint={later} />
        <Tile icon={Server} label={t("home.connect")} hint={later} />
      </div>
    </div>
  );
}
