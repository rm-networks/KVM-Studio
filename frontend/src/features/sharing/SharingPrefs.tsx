import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, type Config, type SharingState } from "../../api/client";
import { useNotifier } from "../../components/notifier";

const MIN_PASSWORD = 8;

interface Props {
  web: Config["web"];
  webMode: boolean;
  onChange: (web: Config["web"]) => void;
}

/** Preferences > Interface: LAN sharing and the guest password (F-100, F-105). */
export function SharingPrefs({ web, webMode, onChange }: Props) {
  const { t } = useTranslation();
  const { notify, notifyError } = useNotifier();
  const [state, setState] = useState<SharingState | null>(null);
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () =>
    api
      .sharing()
      .then(setState)
      .catch(() => setState(null));

  useEffect(() => {
    void load();
  }, []);

  const savePassword = () => {
    setBusy(true);
    api
      .setGuestPassword(password)
      .then(() => {
        setPassword("");
        notify(t("sharing.passwordSet"));
        void load();
      })
      .catch((err: unknown) => notifyError(t("sharing.password"), err))
      .finally(() => setBusy(false));
  };

  return (
    <>
      <label className="prefs-check">
        <input
          type="checkbox"
          checked={web.share_on_lan}
          disabled={!state?.has_password && !web.share_on_lan}
          onChange={(e) => onChange({ ...web, share_on_lan: e.target.checked })}
        />
        {t("sharing.enable")}
      </label>
      <p className="prefs-muted prefs-indent">
        {t(webMode ? "sharing.enableHint" : "sharing.webModeOnly")}
      </p>
      <label className="prefs-field prefs-inline prefs-indent">
        <span>{t("sharing.httpsPort")}</span>
        <input
          type="number"
          min={1024}
          max={65535}
          value={web.https_port}
          onChange={(e) => onChange({ ...web, https_port: Number(e.target.value) })}
        />
      </label>
      <div className="prefs-field prefs-inline prefs-indent">
        <span>{t("sharing.password")}</span>
        <input
          type="password"
          autoComplete="new-password"
          value={password}
          aria-label={t("sharing.password")}
          placeholder={state?.has_password ? t("sharing.passwordKept") : ""}
          onChange={(e) => setPassword(e.target.value)}
        />
        <button
          type="button"
          className="button"
          disabled={busy || password.length < MIN_PASSWORD}
          onClick={savePassword}
        >
          {t("sharing.setPassword")}
        </button>
      </div>
      <p className="prefs-muted prefs-indent">
        {state?.has_password ? t("sharing.passwordHint") : t("sharing.noPassword")}
      </p>
      {state?.active && (
        <div className="prefs-indent">
          <p>{t("sharing.active", { count: state.guests })}</p>
          <ul className="prefs-muted">
            {state.addresses.map((address) => (
              <li key={address} className="mono">
                https://{address}:{state.https_port}/
              </li>
            ))}
          </ul>
          <p className="prefs-muted">
            {t("sharing.fingerprint")} <span className="mono">{state.fingerprint}</span>
          </p>
          <p className="prefs-muted">
            {state.firewall
              ? t("sharing.firewallOpened", { firewall: state.firewall })
              : t("sharing.firewallNone")}
          </p>
        </div>
      )}
    </>
  );
}
