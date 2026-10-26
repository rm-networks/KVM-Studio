import { X } from "lucide-react";
import { type ReactNode, useCallback, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../api/client";
import { type NoticeAction, NotifierContext } from "./notifier";
import "./Notifications.css";

interface Notice {
  id: number;
  title: string;
  error?: ApiError;
  text?: string;
  action?: NoticeAction;
}

let nextId = 1;

export function NotificationProvider({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const [notices, setNotices] = useState<Notice[]>([]);

  const dismiss = useCallback(
    (id: number) => setNotices((list) => list.filter((n) => n.id !== id)),
    [],
  );

  const push = useCallback(
    (notice: Omit<Notice, "id">) => {
      const id = nextId++;
      setNotices((list) => [...list.slice(-3), { ...notice, id }]);
      // Errors and questions stay until closed.
      if (!notice.error && !notice.action) setTimeout(() => dismiss(id), 6000);
      return id;
    },
    [dismiss],
  );

  const notifyError = useCallback(
    (title: string, err: unknown) =>
      push({
        title,
        error: err instanceof ApiError ? err : new ApiError(0, "http.error", String(err)),
      }),
    [push],
  );
  const notify = useCallback(
    (title: string, text?: string, action?: NoticeAction) => push({ title, text, action }),
    [push],
  );

  return (
    <NotifierContext.Provider value={{ notifyError, notify, dismiss }}>
      {children}
      <div className="notices" aria-live="polite">
        {notices.map((n) => (
          <div key={n.id} className={n.error ? "notice notice-error" : "notice"} role="status">
            <div className="notice-head">
              <strong>{n.title}</strong>
              <button
                type="button"
                className="notice-close"
                aria-label={t("about.close")}
                onClick={() => dismiss(n.id)}
              >
                <X />
              </button>
            </div>
            {n.error && (
              <>
                <p>{t(`errors.${n.error.code}`, { defaultValue: t("errors.http.error") })}</p>
                {n.error.detail && (
                  <details>
                    <summary>{t("errors.details")}</summary>
                    <pre>{n.error.detail}</pre>
                  </details>
                )}
              </>
            )}
            {n.text && <p>{n.text}</p>}
            {n.action && (
              <div className="notice-actions">
                <button
                  type="button"
                  className="button"
                  onClick={() => {
                    dismiss(n.id);
                    n.action?.run();
                  }}
                >
                  {n.action.label}
                </button>
              </div>
            )}
          </div>
        ))}
      </div>
    </NotifierContext.Provider>
  );
}
