import { useTranslation } from "react-i18next";

import animated from "../assets/loading-cubes.svg";
import still from "../assets/loading-cubes-static.svg";
import "./LoadingCubes.css";

/** KVM Studio cubes while something loads; the still picture when animations are off. */
export function LoadingCubes({ message }: { message?: string }) {
  const { t } = useTranslation();
  return (
    <div className="loading-cubes" role="status">
      <picture>
        <source srcSet={still} media="(prefers-reduced-motion: reduce)" />
        <img src={animated} alt="" width={96} height={96} />
      </picture>
      <span className="loading-cubes-name">{t("loading.brand")}</span>
      {message && <span className="loading-cubes-message">{message}</span>}
    </div>
  );
}
