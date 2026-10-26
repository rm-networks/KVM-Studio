import { CircleCheck, CircleX, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, type Config, type GroupState, type SetupStatus } from "../../api/client";
import { Wizard } from "../../components/Wizard";
import { useNotifier } from "../../components/notifier";
import { LANGUAGE_NAMES, type Language, languages } from "../../i18n";
import { folderPicker } from "../../platform/folders";
import { RestartPrompt } from "../preferences/PreferencesDialog";
import "./FirstRunWizard.css";

const STEPS = ["welcome", "checks", "group", "locations", "mode", "networks", "done"] as const;
type Step = (typeof STEPS)[number];

const LEVEL_ICON = { ok: CircleCheck, warn: TriangleAlert, fail: CircleX } as const;

interface Props {
  onClose: () => void;
  /** Called once the settings are saved, so the main window reloads them. */
  onSaved: () => void;
}

function FolderInput({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const { t } = useTranslation();
  const pick = folderPicker();
  return (
    <span className="field-with-button">
      <input type="text" value={value} onChange={(e) => onChange(e.target.value)} />
      {pick && (
        <button
          type="button"
          className="button"
          onClick={() => void pick(value || null).then((path) => path && onChange(path))}
        >
          {t("prefs.browse")}
        </button>
      )}
    </span>
  );
}

export function FirstRunWizard({ onClose, onSaved }: Props) {
  const { t, i18n } = useTranslation();
  const { notifyError } = useNotifier();
  const [step, setStep] = useState<Step>("welcome");
  const [status, setStatus] = useState<SetupStatus | null>(null);
  const [config, setConfig] = useState<Config | null>(null);
  const [group, setGroup] = useState<GroupState | null>(null);
  const [vmLocation, setVmLocation] = useState("");
  const [isoPath, setIsoPath] = useState("");
  const [mode, setMode] = useState<"desktop" | "web">("desktop");
  const [createNetworks, setCreateNetworks] = useState(true);
  const [busy, setBusy] = useState(false);
  const [created, setCreated] = useState<string[]>([]);
  const [restart, setRestart] = useState<Config | null>(null);
  const [language, setLanguage] = useState<Language>("en");
  const [showRestart, setShowRestart] = useState(false);

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.setup(), api.preferences()])
      .then(([s, prefs]) => {
        if (cancelled) return;
        setStatus(s);
        setGroup(s.libvirt_group);
        setConfig(prefs.config);
        setLanguage(prefs.config.ui.language);
        setVmLocation(prefs.config.storage.vm_default_location ?? "");
        setMode(prefs.config.interface.mode);
        setCreateNetworks(s.networks.some((n) => !n.exists));
      })
      .catch((err: unknown) => !cancelled && notifyError(t("firstRun.title"), err));
    return () => {
      cancelled = true;
    };
  }, [notifyError, t]);

  const index = STEPS.indexOf(step);
  const locationValid = vmLocation.startsWith("/");
  const isoValid = isoPath === "" || isoPath.startsWith("/");
  const ready: Record<Step, boolean> = {
    welcome: true,
    checks: status !== null,
    group: true,
    locations: locationValid && isoValid,
    mode: true,
    networks: config !== null,
    done: true,
  };

  const joinGroup = async () => {
    setBusy(true);
    try {
      setGroup((await api.joinLibvirtGroup()).libvirt_group);
    } catch (err) {
      notifyError(t("firstRun.group.failed"), err);
    } finally {
      setBusy(false);
    }
  };

  // Applied at once, and saved, so that the rest of the assistant speaks it.
  const chooseLanguage = (next: Language) => {
    setLanguage(next);
    void i18n.changeLanguage(next);
    if (!config) return;
    const updated: Config = { ...config, ui: { ...config.ui, language: next } };
    setConfig(updated);
    api
      .savePreferences(updated)
      .then(onSaved)
      .catch((err: unknown) => notifyError(t("firstRun.failed"), err));
  };

  const apply = async () => {
    if (!config) return;
    setBusy(true);
    const next: Config = {
      ...config,
      storage: { ...config.storage, vm_default_location: vmLocation },
      interface: { ...config.interface, mode },
    };
    try {
      const result = await api.savePreferences(next);
      // Declared to the helper, which asks for the administrator password.
      if (isoPath && !config.iso_libraries.some((lib) => lib.path === isoPath)) {
        await api.addIsoLibrary({
          name: t("firstRun.locations.isoName"),
          path: isoPath,
          recursive: true,
        });
      }
      onSaved();
      if (createNetworks) setCreated(await api.createDefaultNetworks());
      if (result.restart_required) setRestart(next);
      setStep("done");
    } catch (err) {
      notifyError(t("firstRun.failed"), err);
    } finally {
      setBusy(false);
    }
  };

  if (showRestart && restart) return <RestartPrompt next={restart} onClose={onClose} />;

  const finish = () => (restart ? setShowRestart(true) : onClose());

  return (
    <Wizard
      name={t("firstRun.title")}
      title={step === "welcome" ? t("firstRun.title") : t(`firstRun.step.${step}`)}
      step={index}
      steps={STEPS.length}
      onCancel={() => !busy && onClose()}
      buttons={
        step === "done" ? (
          <button type="button" className="button button-primary" onClick={finish}>
            {t("firstRun.close")}
          </button>
        ) : (
          <>
            <button type="button" className="button" disabled={busy} onClick={onClose}>
              {t("common.cancel")}
            </button>
            <button
              type="button"
              className="button"
              disabled={index === 0 || busy}
              onClick={() => setStep(STEPS[index - 1] ?? step)}
            >
              {t("wizard.back")}
            </button>
            {step === "networks" ? (
              <button
                type="button"
                className="button button-primary"
                disabled={busy || !ready.networks}
                onClick={() => void apply()}
              >
                {busy ? t("firstRun.applying") : t("wizard.finish")}
              </button>
            ) : (
              <button
                type="button"
                className="button button-primary"
                disabled={busy || !ready[step]}
                onClick={() => setStep(STEPS[index + 1] ?? step)}
              >
                {t("wizard.next")}
              </button>
            )}
          </>
        )
      }
    >
      {step === "welcome" && (
        <>
          <fieldset className="first-run-language">
            <legend>{t("firstRun.welcome.language")}</legend>
            {languages.map((code) => (
              <label key={code} className="check">
                <input
                  type="radio"
                  name="language"
                  checked={language === code}
                  onChange={() => chooseLanguage(code)}
                />
                {LANGUAGE_NAMES[code]}
              </label>
            ))}
          </fieldset>
          <p>{t("firstRun.welcome.intro")}</p>
          <p>{t("firstRun.welcome.license")}</p>
          <p className="muted">{t("about.notice")}</p>
        </>
      )}

      {step === "checks" && status && (
        <ul className="checklist">
          {status.checks.map((c) => {
            const Icon = LEVEL_ICON[c.level];
            return (
              <li key={c.id} className={`checklist-${c.level}`}>
                <Icon aria-hidden />
                <span>
                  {t(`firstRun.check.${c.id}.${c.level}`, { detail: c.detail })}
                  {c.level !== "ok" && (
                    <small>
                      {c.id === "kvm" && c.detail
                        ? t(`errors.kvm.${c.detail}`)
                        : t(`firstRun.check.${c.id}.hint`, { detail: c.detail })}
                    </small>
                  )}
                </span>
              </li>
            );
          })}
        </ul>
      )}

      {step === "group" && group && (
        <>
          <p>{t("firstRun.group.why")}</p>
          <p className={group === "member" || group === "not_needed" ? "note" : "note note-warn"}>
            {t(`firstRun.group.state.${group}`, { user: status?.user })}
          </p>
          {group === "not_member" && (
            <button
              type="button"
              className="button"
              disabled={busy}
              onClick={() => void joinGroup()}
            >
              {t("firstRun.group.join")}
            </button>
          )}
        </>
      )}

      {step === "locations" && (
        <>
          <label className="field">
            <span>{t("firstRun.locations.vm")}</span>
            <FolderInput value={vmLocation} onChange={setVmLocation} />
            <span className="muted">{t("firstRun.locations.vmHint")}</span>
          </label>
          <label className="field">
            <span>{t("firstRun.locations.iso")}</span>
            <FolderInput value={isoPath} onChange={setIsoPath} />
            <span className="muted">{t("firstRun.locations.isoHint")}</span>
          </label>
          {!isoValid && <p className="field-error">{t("firstRun.locations.absolute")}</p>}
        </>
      )}

      {step === "mode" && (
        <>
          {(["desktop", "web"] as const).map((m) => (
            <div key={m}>
              <label className="check">
                <input type="radio" checked={mode === m} onChange={() => setMode(m)} />
                {t(`firstRun.mode.${m}`)}
              </label>
              <p className="check-hint">{t(`firstRun.mode.${m}Hint`)}</p>
            </div>
          ))}
        </>
      )}

      {step === "networks" && status && (
        <>
          <p>{t("firstRun.networks.intro")}</p>
          <table className="facts firstrun-networks">
            <tbody>
              {status.networks.map((n) => (
                <tr key={n.name}>
                  <td>{n.name}</td>
                  <td>{t(`networks.kind.${n.kind}`)}</td>
                  <td>{n.subnet}</td>
                  <td>{n.exists ? t("firstRun.networks.exists") : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {status.networks.some((n) => !n.exists) && (
            <label className="check">
              <input
                type="checkbox"
                checked={createNetworks}
                onChange={(e) => setCreateNetworks(e.target.checked)}
              />
              {t("firstRun.networks.create")}
            </label>
          )}
        </>
      )}

      {step === "done" && (
        <>
          <p>{t("firstRun.done.saved")}</p>
          {created.length > 0 && (
            <p>{t("firstRun.done.networks", { names: created.join(", ") })}</p>
          )}
          {group === "relogin" && <p className="note note-warn">{t("firstRun.group.relogin")}</p>}
          <p>{t("close.why")}</p>
          <p className="muted">{t("firstRun.done.again")}</p>
        </>
      )}
    </Wizard>
  );
}
