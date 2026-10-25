import { CircleAlert } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { ApiError } from "../api/client";
import "./ErrorMessage.css";

interface Props {
  error: ApiError;
  onRetry?: () => void;
}

export function ErrorMessage({ error, onRetry }: Props) {
  const { t } = useTranslation();
  const message = t(`errors.${error.code}`, { defaultValue: t("errors.http.error") });

  return (
    <div className="error-message" role="alert">
      <div className="error-message-head">
        <CircleAlert aria-hidden />
        <span>{message}</span>
      </div>
      {error.detail && (
        <details>
          <summary>{t("errors.details")}</summary>
          <pre>{error.detail}</pre>
        </details>
      )}
      {onRetry && (
        <button type="button" className="button error-message-retry" onClick={onRetry}>
          {t("errors.retry")}
        </button>
      )}
    </div>
  );
}
