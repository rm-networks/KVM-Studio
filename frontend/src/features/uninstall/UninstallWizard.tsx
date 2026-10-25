import { CircleCheck, CircleX, Loader, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, ApiError, type UninstallPlan, type UninstallReport } from "../../api/client";
import { Wizard } from "../../components/Wizard";
import { ErrorMessage } from "../../components/ErrorMessage";
import "../first-run/FirstRunWizard.css";
import "./UninstallWizard.css";

const STEPS = [
  "welcome",
  "vms",
  "networks",
  "rights",
  "settings",
  "summary",
  "progress",
  "done",
] as const;
type Step = (typeof STEPS)[number];
type Task = "vms" | "networks" | "rights" | "settings" | "package";
type TaskState = "pending" | "running" | "done" | "skipped" | "failed";

// Time left to the package manager before the assistant stops waiting.
const PACKAGE_TIMEOUT_MS = 10 * 60 * 1000;
const POLL_MS = 2000;

function closeWindow() {
  const api = window.pywebview?.api;
  if (api?.close_window) void api.close_window();
  else window.close();
}

function Choice({
  name,
  value,
  onChange,
  keepLabel,
  deleteLabel,
}: {
  name: string;
  value: boolean;
  onChange: (remove: boolean) => void;
  keepLabel: string;
  deleteLabel: string;
}) {
  return (
    <>
      <label className="check">
        <input type="radio" name={name} checked={!value} onChange={() => onChange(false)} />
        {keepLabel}
      </label>
      <label className="check">
        <input type="radio" name={name} checked={value} onChange={() => onChange(true)} />
        {deleteLabel}
      </label>
    </>
  );
}

export function UninstallWizard() {
  const { t } = useTranslation();
  const [step, setStep] = useState<Step>("welcome");
  const [plan, setPlan] = useState<UninstallPlan | null>(null);
  const [error, setFailure] = useState<ApiError | null>(null);
  const setError = (err: unknown) =>
    setFailure(err instanceof ApiError ? err : new ApiError(0, "http.error", String(err)));
  const [deleteVms, setDeleteVms] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [deleteNetworks, setDeleteNetworks] = useState(false);
  const [deleteSettings, setDeleteSettings] = useState(false);
  const [removeRights, setRemoveRights] = useState(false);
  const [tasks, setTasks] = useState<Record<Task, TaskState>>({
    vms: "pending",
    networks: "pending",
    rights: "pending",
    settings: "pending",
    package: "pending",
  });
  const [report, setReport] = useState<UninstallReport | null>(null);

  useEffect(() => {
    document.title = t("uninstall.title");
    let cancelled = false;
    api
      .uninstallPlan()
      .then((p) => !cancelled && setPlan(p))
      .catch((err: unknown) => !cancelled && setError(err));
    return () => {
      cancelled = true;
    };
  }, [t]);

  const rights = plan ? plan.iso_libraries.length + plan.iso_acl_entries > 0 : false;
  const files = plan ? [...plan.vms.flatMap((vm) => vm.delete), ...plan.extra_files] : [];
  const kept = plan ? [...plan.vms.flatMap((vm) => vm.keep), ...plan.keep] : [];
  const blocked = deleteVms && (plan?.running.length ?? 0) > 0;
  const index = STEPS.indexOf(step);
  const ready: Partial<Record<Step, boolean>> = {
    welcome: plan !== null,
    vms: !deleteVms || (confirmed && !blocked),
  };

  const networkUsers = (n: UninstallPlan["networks"][number]) =>
    deleteVms ? n.used_by_kept : [...n.used_by_kept, ...n.used_by_deleted];

  const mark = (task: Task, state: TaskState) => setTasks((s) => ({ ...s, [task]: state }));

  const waitForRemoval = async () => {
    const until = Date.now() + PACKAGE_TIMEOUT_MS;
    while (Date.now() < until) {
      await new Promise((r) => setTimeout(r, POLL_MS));
      try {
        if (!(await api.packageState()).present) return true;
      } catch {
        // The server may stop answering while its files go away: keep trying.
      }
    }
    return false;
  };

  const run = async () => {
    if (!plan) return;
    setStep("progress");
    setTasks({
      vms: deleteVms ? "running" : "skipped",
      networks: deleteNetworks ? "running" : "skipped",
      rights: rights && removeRights ? "running" : "skipped",
      settings: deleteSettings ? "running" : "skipped",
      package: plan.packaged ? "pending" : "skipped",
    });
    try {
      const result = await api.uninstall({
        plan_id: plan.plan_id,
        delete_vms: deleteVms,
        delete_networks: deleteNetworks,
        delete_settings: deleteSettings,
        remove_iso_acls: removeRights,
      });
      setReport(result);
      if (deleteVms) mark("vms", result.failed_files.length ? "failed" : "done");
      if (deleteNetworks) mark("networks", "done");
      if (rights && removeRights) mark("rights", result.iso_failed ? "failed" : "done");
      if (deleteSettings) mark("settings", result.deleted_settings ? "done" : "failed");
    } catch (err) {
      setError(err);
      setTasks((s) => ({
        vms: s.vms === "running" ? "failed" : s.vms,
        networks: s.networks === "running" ? "failed" : s.networks,
        rights: s.rights === "running" ? "failed" : s.rights,
        settings: s.settings === "running" ? "failed" : s.settings,
        package: "skipped",
      }));
      setStep("done");
      return;
    }
    if (plan.packaged) {
      mark("package", "running");
      try {
        await api.removePackage();
        mark("package", (await waitForRemoval()) ? "done" : "failed");
      } catch (err) {
        setError(err);
        mark("package", "failed");
      }
    }
    setStep("done");
  };

  const TASK_ICON = {
    pending: null,
    running: <Loader className="spin" aria-hidden />,
    done: <CircleCheck aria-hidden />,
    skipped: null,
    failed: <CircleX aria-hidden />,
  } as const;

  const choice = (remove: boolean) => (remove ? t("uninstall.delete") : t("uninstall.keep"));
  const buttons =
    step === "progress" ? null : step === "done" ? (
      <button type="button" className="button button-primary" onClick={closeWindow}>
        {t("firstRun.close")}
      </button>
    ) : (
      <>
        <button type="button" className="button" onClick={closeWindow}>
          {t("common.cancel")}
        </button>
        <button
          type="button"
          className="button"
          disabled={index === 0}
          onClick={() => setStep(STEPS[index - 1] ?? step)}
        >
          {t("wizard.back")}
        </button>
        {step === "summary" ? (
          <button type="button" className="button button-danger" onClick={() => void run()}>
            {t("uninstall.run")}
          </button>
        ) : (
          <button
            type="button"
            className="button button-primary"
            disabled={ready[step] === false}
            onClick={() => setStep(STEPS[index + 1] ?? step)}
          >
            {t("wizard.next")}
          </button>
        )}
      </>
    );

  return (
    <Wizard
      name={t("uninstall.title")}
      title={step === "welcome" ? t("uninstall.title") : t(`uninstall.step.${step}`)}
      step={index}
      steps={STEPS.length}
      mode="window"
      buttons={buttons}
    >
      {error !== null && step !== "done" && <ErrorMessage error={error} />}

      {step === "welcome" && (
        <>
          <p>{t("uninstall.welcome.intro")}</p>
          <p>{t("uninstall.welcome.choices")}</p>
        </>
      )}

      {step === "vms" && plan && (
        <>
          {plan.vms.length === 0 ? (
            <p>{t("uninstall.vms.none")}</p>
          ) : (
            <>
              <Choice
                name="vms"
                value={deleteVms}
                onChange={(v) => {
                  setDeleteVms(v);
                  setConfirmed(false);
                }}
                keepLabel={t("uninstall.vms.keep")}
                deleteLabel={t("uninstall.vms.delete", { count: plan.vms.length })}
              />
              {deleteVms && (
                <div className="code-box">
                  {plan.vms.map((vm) => (
                    <div key={vm.uuid}>
                      <strong>{vm.name}</strong>
                      <ul>
                        {vm.delete.map((path) => (
                          <li key={path}>{path}</li>
                        ))}
                      </ul>
                    </div>
                  ))}
                  {plan.extra_files.length > 0 && (
                    <div>
                      <strong>{t("uninstall.vms.extra")}</strong>
                      <ul>
                        {plan.extra_files.map((path) => (
                          <li key={path}>{path}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {kept.length > 0 && (
                    <div>
                      <strong>{t("uninstall.vms.kept")}</strong>
                      <ul>
                        {kept.map((k) => (
                          <li key={k.path}>
                            {k.path} ({t(`delete.reason.${k.reason}`)})
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}
              {deleteVms && blocked && (
                <p className="note note-warn">
                  <TriangleAlert aria-hidden />
                  {t("uninstall.vms.running", { names: plan.running.join(", ") })}
                </p>
              )}
              {deleteVms && !blocked && (
                <label className="check">
                  <input
                    type="checkbox"
                    checked={confirmed}
                    onChange={(e) => setConfirmed(e.target.checked)}
                  />
                  {t("uninstall.vms.confirm", { count: files.length })}
                </label>
              )}
            </>
          )}
          {plan.kept_vms.length > 0 && (
            <p className="muted">
              {t("uninstall.vms.foreign", { names: plan.kept_vms.join(", ") })}
            </p>
          )}
        </>
      )}

      {step === "networks" && plan && (
        <>
          {plan.networks.length === 0 ? (
            <p>{t("uninstall.networks.none")}</p>
          ) : (
            <>
              <Choice
                name="networks"
                value={deleteNetworks}
                onChange={setDeleteNetworks}
                keepLabel={t("uninstall.networks.keep")}
                deleteLabel={t("uninstall.networks.delete")}
              />
              <table className="facts">
                <tbody>
                  {plan.networks.map((n) => {
                    const users = networkUsers(n);
                    return (
                      <tr key={n.name}>
                        <td>{n.name}</td>
                        <td>{n.bridge}</td>
                        <td>
                          {users.length > 0 &&
                            t("uninstall.networks.usedBy", { names: users.join(", ") })}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </>
          )}
        </>
      )}

      {step === "rights" && plan && (
        <>
          {!rights ? (
            <p>{t("uninstall.rights.none")}</p>
          ) : (
            <>
              <p>{t("uninstall.rights.intro", { count: plan.iso_acl_entries })}</p>
              <Choice
                name="rights"
                value={removeRights}
                onChange={setRemoveRights}
                keepLabel={t("uninstall.rights.keep")}
                deleteLabel={t("uninstall.rights.delete")}
              />
              <ul className="code-box uninstall-paths">
                {plan.iso_libraries.map((path) => (
                  <li key={path}>{path}</li>
                ))}
              </ul>
            </>
          )}
        </>
      )}

      {step === "settings" && plan && (
        <>
          {plan.settings.length === 0 ? (
            <p>{t("uninstall.settings.none")}</p>
          ) : (
            <>
              <Choice
                name="settings"
                value={deleteSettings}
                onChange={setDeleteSettings}
                keepLabel={t("uninstall.settings.keep")}
                deleteLabel={t("uninstall.settings.delete")}
              />
              <ul className="code-box uninstall-paths">
                {plan.settings.map((path) => (
                  <li key={path}>{path}</li>
                ))}
              </ul>
            </>
          )}
        </>
      )}

      {step === "summary" && plan && (
        <table className="facts">
          <tbody>
            <tr>
              <td>{t("uninstall.step.vms")}</td>
              <td>{plan.vms.length ? choice(deleteVms) : "-"}</td>
            </tr>
            <tr>
              <td>{t("uninstall.step.networks")}</td>
              <td>{plan.networks.length ? choice(deleteNetworks) : "-"}</td>
            </tr>
            <tr>
              <td>{t("uninstall.step.rights")}</td>
              <td>{rights ? choice(removeRights) : "-"}</td>
            </tr>
            <tr>
              <td>{t("uninstall.step.settings")}</td>
              <td>{plan.settings.length ? choice(deleteSettings) : "-"}</td>
            </tr>
            <tr>
              <td>{t("uninstall.task.package")}</td>
              <td>{plan.packaged ? t("uninstall.packageRemove") : t("uninstall.notPackaged")}</td>
            </tr>
          </tbody>
        </table>
      )}

      {(step === "progress" || step === "done") && (
        <ul className="checklist">
          {(["vms", "networks", "rights", "settings", "package"] as const).map((task) => (
            <li key={task} className={`checklist-${tasks[task]}`}>
              {TASK_ICON[tasks[task]] ?? <span className="checklist-blank" />}
              <span>
                {t(`uninstall.task.${task}`)}
                <small>{t(`uninstall.state.${tasks[task]}`)}</small>
              </span>
            </li>
          ))}
        </ul>
      )}

      {step === "progress" && tasks.package === "running" && (
        <p className="muted">{t("uninstall.packageWait")}</p>
      )}

      {step === "done" && (
        <>
          {error !== null && <ErrorMessage error={error} />}
          {report && report.failed_files.length > 0 && (
            <>
              <p>{t("uninstall.failedFiles")}</p>
              <ul className="code-box uninstall-paths">
                {report.failed_files.map((path) => (
                  <li key={path}>{path}</li>
                ))}
              </ul>
            </>
          )}
          {report && report.kept_networks.length > 0 && (
            <p>{t("uninstall.keptNetworks", { names: report.kept_networks.join(", ") })}</p>
          )}
          {error === null && <p>{t("uninstall.finished")}</p>}
        </>
      )}
    </Wizard>
  );
}
