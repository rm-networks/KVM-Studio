import { CircleCheck, CircleX, Loader, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, ApiError, type UninstallPlan, type UninstallReport } from "../../api/client";
import { Dialog } from "../../components/Dialog";
import { ErrorMessage } from "../../components/ErrorMessage";
import "../wizard/NewVmWizard.css";
import "../first-run/FirstRunWizard.css";
import "./UninstallWizard.css";

const STEPS = ["welcome", "vms", "networks", "settings", "summary", "progress", "done"] as const;
type Step = (typeof STEPS)[number];
type Task = "vms" | "networks" | "settings" | "package";
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
      <label className="wizard-choice">
        <input type="radio" name={name} checked={!value} onChange={() => onChange(false)} />
        {keepLabel}
      </label>
      <label className="wizard-choice">
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
  const [tasks, setTasks] = useState<Record<Task, TaskState>>({
    vms: "pending",
    networks: "pending",
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
      settings: deleteSettings ? "running" : "skipped",
      package: plan.packaged ? "pending" : "skipped",
    });
    try {
      const result = await api.uninstall({
        plan_id: plan.plan_id,
        delete_vms: deleteVms,
        delete_networks: deleteNetworks,
        delete_settings: deleteSettings,
      });
      setReport(result);
      if (deleteVms) mark("vms", result.failed_files.length ? "failed" : "done");
      if (deleteNetworks) mark("networks", "done");
      if (deleteSettings) mark("settings", result.deleted_settings ? "done" : "failed");
    } catch (err) {
      setError(err);
      setTasks((s) => ({
        vms: s.vms === "running" ? "failed" : s.vms,
        networks: s.networks === "running" ? "failed" : s.networks,
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
    running: <Loader size={14} className="uninstall-spin" aria-hidden />,
    done: <CircleCheck size={14} aria-hidden />,
    skipped: null,
    failed: <CircleX size={14} aria-hidden />,
  } as const;

  const choice = (remove: boolean) => (remove ? t("uninstall.delete") : t("uninstall.keep"));
  const buttons =
    step === "progress" ? null : step === "done" ? (
      <button type="button" className="button button-primary" onClick={closeWindow}>
        {t("firstRun.close")}
      </button>
    ) : (
      <>
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
        <button type="button" className="button" onClick={closeWindow}>
          {t("common.cancel")}
        </button>
      </>
    );

  return (
    <Dialog
      open
      width={700}
      onOpenChange={(open) => !open && step !== "progress" && closeWindow()}
      title={t("uninstall.title")}
      buttons={buttons}
    >
      <ol className="wizard-steps">
        {STEPS.map((s) => (
          <li key={s} className={s === step ? "current" : undefined}>
            {t(`uninstall.step.${s}`)}
          </li>
        ))}
      </ol>

      <div className="wizard-page">
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
                  <div className="uninstall-files">
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
                  <p className="firstrun-warn">
                    <TriangleAlert size={13} aria-hidden />{" "}
                    {t("uninstall.vms.running", { names: plan.running.join(", ") })}
                  </p>
                )}
                {deleteVms && !blocked && (
                  <label className="wizard-choice">
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
              <p className="firstrun-muted">
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
                <table className="firstrun-table">
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
                <ul className="uninstall-files">
                  {plan.settings.map((path) => (
                    <li key={path}>{path}</li>
                  ))}
                </ul>
              </>
            )}
          </>
        )}

        {step === "summary" && plan && (
          <table className="firstrun-table">
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
          <ul className="firstrun-checks">
            {(["vms", "networks", "settings", "package"] as const).map((task) => (
              <li key={task} className={`uninstall-${tasks[task]}`}>
                {TASK_ICON[tasks[task]] ?? <span className="uninstall-blank" />}
                <span>
                  {t(`uninstall.task.${task}`)}
                  <small>{t(`uninstall.state.${tasks[task]}`)}</small>
                </span>
              </li>
            ))}
          </ul>
        )}

        {step === "progress" && tasks.package === "running" && (
          <p className="firstrun-muted">{t("uninstall.packageWait")}</p>
        )}

        {step === "done" && (
          <>
            {error !== null && <ErrorMessage error={error} />}
            {report && report.failed_files.length > 0 && (
              <>
                <p>{t("uninstall.failedFiles")}</p>
                <ul className="uninstall-files">
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
      </div>
    </Dialog>
  );
}
