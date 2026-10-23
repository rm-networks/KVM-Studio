import { House } from "lucide-react";
import { useTranslation } from "react-i18next";

import "./TabBar.css";

export function TabBar() {
  const { t } = useTranslation();
  return (
    <div className="tabbar" role="tablist">
      <div className="tab" role="tab" aria-selected="true">
        <House size={13} aria-hidden />
        <span>{t("home.tab")}</span>
      </div>
    </div>
  );
}
