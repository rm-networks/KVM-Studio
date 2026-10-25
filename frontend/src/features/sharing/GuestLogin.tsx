import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, ApiError } from "../../api/client";
import { APP_NAME } from "../../brand";
import "./GuestLogin.css";

/** LAN sharing: the guest password opens a session (cookie) for this browser. */
export function GuestLogin({ onLoggedIn }: { onLoggedIn: () => void }) {
  const { t } = useTranslation();
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    api
      .login(password)
      .then(onLoggedIn)
      .catch((err: unknown) => {
        const code = err instanceof ApiError ? err.code : "http.error";
        setError(
          t(`errors.${code}`, {
            defaultValue: t("errors.http.error"),
            detail: err instanceof ApiError ? err.detail : "",
          }),
        );
        setPassword("");
        setBusy(false);
      });
  };

  return (
    <main className="guest-login">
      <form className="guest-login-box" onSubmit={submit}>
        <img src="/logo.png" alt="" width={48} height={48} />
        <h1>{APP_NAME}</h1>
        <p className="muted">{t("guest.intro")}</p>
        <label>
          {t("guest.password")}
          <input
            type="password"
            autoComplete="current-password"
            autoFocus
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        {error && (
          <p className="field-error" role="alert">
            {error}
          </p>
        )}
        <button type="submit" className="button button-primary" disabled={busy || !password}>
          {t("guest.login")}
        </button>
      </form>
    </main>
  );
}
