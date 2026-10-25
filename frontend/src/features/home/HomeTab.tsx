import { Plus } from "lucide-react";
import { useTranslation } from "react-i18next";

import { APP_NAME } from "../../brand";
import "./HomeTab.css";

export function HomeTab({ onNewVm }: { onNewVm: () => void }) {
  const { t } = useTranslation();
  return (
    <div className="home">
      <img className="home-logo" src="/logo.png" alt="" width={64} height={64} />
      <h1 className="home-title">{APP_NAME}</h1>
      <button type="button" className="button home-action" onClick={onNewVm}>
        <Plus aria-hidden />
        {t("home.create")}
      </button>
    </div>
  );
}
