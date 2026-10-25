import { X } from "lucide-react";
import { type ReactNode, useCallback, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../api/client";
import { NotifierContext } from "./notifier";
import "./Notifications.css";

interface Notice {
  id: number;
  title: string;
  error?: ApiError;
  text?: string;
}

let nextId = 1;

export function NotificationProvider({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const [notices, setNotices] = useState<Notice[]>([]);

  const dismiss = (id: number) => setNotices((list) => list.filter((n) => n.id !== id));

  const push = useCallback((notice: Omit<Notice, "id">) => {
    const id = nextId++;
    setNotices((list) => [...list.slice(-3), { ...notice, id }]);
    if (!notice.error) setTimeout(() => dismiss(id), 6000);
  }, []);

  const notifyError = useCallback(
    (title: string, err: unknown) =>
      push({
        title,
        error: err instanceof ApiError ? err : new ApiError(0, "http.error", String(err)),
      }),
    [push],
  );
  const notify = useCallback((title: string, text?: string) => push({ title, text }), [push]);

  return (
    <NotifierContext.Provider value={{ notifyError, notify }}>
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
          </div>
        ))}
      </div>
    </NotifierContext.Provider>
  );
}
