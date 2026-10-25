import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, type Config, type RunningVm } from "../../api/client";
import { Dialog } from "../../components/Dialog";
import { useNotifier } from "../../components/notifier";
import "../vm/DeleteDialog.css";

export type CloseReason = "quit" | "switch";

// Clean shutdown: how long the guests get before offering to force.
const SHUTDOWN_WAIT_S = 60;
const POLL_MS = 2000;

type Step =
  | { kind: "loading" }
  | { kind: "reminder" }
  | { kind: "ask" }
  | { kind: "suspending" }
  | { kind: "stopping"; left: number }
  | { kind: "stuck" };

interface Props {
  reason: CloseReason;
  onProceed: () => void;
  onCancel: () => void;
}

/**
 * Before KVM Studio closes or changes mode: VMs are run by libvirt and QEMU and
 * keep running, unless Preferences > Workspace says to suspend or shut them down.
 */
export function CloseDialog({ reason, onProceed, onCancel }: Props) {
  const { t } = useTranslation();
  const { notifyError } = useNotifier();
  const [step, setStep] = useState<Step>({ kind: "loading" });
  const [vms, setVms] = useState<RunningVm[]>([]);
  const [config, setConfig] = useState<Config | null>(null);
  const [hideReminder, setHideReminder] = useState(false);
  const proceeded = useRef(false);

  const proceed = useCallback(() => {
    if (proceeded.current) return;
    proceeded.current = true;
    onProceed();
  }, [onProceed]);

  const suspend = useCallback(() => {
    setStep({ kind: "suspending" });
    api
      .closeAction("suspend")
      .then((result) => {
        if (result.failed.length === 0) proceed();
        else {
          setVms(result.failed.map((f) => ({ uuid: f.name, name: f.name })));
          setStep({ kind: "stuck" });
        }
      })
      .catch((err: unknown) => {
        notifyError(t("close.failed"), err);
        setStep({ kind: "stuck" });
      });
  }, [proceed, notifyError, t]);

  const shutdown = useCallback(() => {
    setStep({ kind: "stopping", left: SHUTDOWN_WAIT_S });
    api.closeAction("shutdown").catch((err: unknown) => notifyError(t("close.failed"), err));
  }, [notifyError, t]);

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.runningVms(), api.preferences()])
      .then(([running, prefs]) => {
        if (cancelled) return;
        setVms(running);
        setConfig(prefs.config);
        const policy = prefs.config.workspace.on_close;
        if (running.length === 0) proceed();
        else if (policy === "ask") setStep({ kind: "ask" });
        else if (policy === "suspend") suspend();
        else if (policy === "shutdown") shutdown();
        else if (prefs.config.workspace.close_reminder) setStep({ kind: "reminder" });
        else proceed();
      })
      // Without an answer from the backend there is nothing to protect.
      .catch(() => !cancelled && proceed());
    return () => {
      cancelled = true;
    };
  }, [proceed, suspend, shutdown]);

  // While the guests shut down: follow which ones still run, then offer to force.
  const stopping = step.kind === "stopping";
  useEffect(() => {
    if (!stopping) return;
    const started = Date.now();
    const timer = setInterval(() => {
      api
        .runningVms()
        .then((running) => {
          setVms(running);
          const left = SHUTDOWN_WAIT_S - Math.round((Date.now() - started) / 1000);
          if (running.length === 0) proceed();
          else if (left <= 0) setStep({ kind: "stuck" });
          else setStep({ kind: "stopping", left });
        })
        .catch(() => undefined);
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [stopping, proceed]);

  const keep = () => {
    if (hideReminder && config) {
      const next = { ...config, workspace: { ...config.workspace, close_reminder: false } };
      api.savePreferences(next).catch(() => undefined);
    }
    proceed();
  };

  const go = reason === "quit" ? t("close.quit") : t("close.restart");
  const list = (
    <ul className="delete-files">
      {vms.map((vm) => (
        <li key={vm.uuid}>{vm.name}</li>
      ))}
    </ul>
  );
  const cancel = (
    <button type="button" className="button" onClick={onCancel}>
      {t("common.cancel")}
    </button>
  );

  if (step.kind === "loading") return null;

  return (
    <Dialog
      open
      width={520}
      onOpenChange={(open) => !open && onCancel()}
      title={reason === "quit" ? t("close.titleQuit") : t("close.titleSwitch")}
      buttons={
        step.kind === "reminder" ? (
          <>
            <button type="button" className="button button-primary" onClick={keep} autoFocus>
              {go}
            </button>
            {cancel}
          </>
        ) : step.kind === "ask" ? (
          <>
            <button type="button" className="button button-primary" onClick={proceed} autoFocus>
              {t("close.keepRunning")}
            </button>
            <button type="button" className="button" onClick={suspend}>
              {t("close.suspend")}
            </button>
            <button type="button" className="button" onClick={shutdown}>
              {t("close.shutdown")}
            </button>
            {cancel}
          </>
        ) : step.kind === "stuck" ? (
          <>
            <button
              type="button"
              className="button button-danger"
              onClick={() =>
                void api
                  .closeAction("poweroff")
                  .then(proceed)
                  .catch((err: unknown) => notifyError(t("close.failed"), err))
              }
            >
              {t("close.powerOff")}
            </button>
            <button type="button" className="button" onClick={proceed}>
              {t("close.leaveRunning")}
            </button>
            {cancel}
          </>
        ) : (
          cancel
        )
      }
    >
      {(step.kind === "reminder" || step.kind === "ask") && (
        <>
          <p>{t("close.stillRunning", { count: vms.length })}</p>
          {list}
          <p className="delete-muted">{t("close.why")}</p>
        </>
      )}
      {step.kind === "reminder" && (
        <label className="check">
          <input
            type="checkbox"
            checked={hideReminder}
            onChange={(e) => setHideReminder(e.target.checked)}
          />
          {t("close.dontShow")}
        </label>
      )}
      {step.kind === "suspending" && <p>{t("close.suspending")}</p>}
      {step.kind === "stopping" && (
        <>
          <p>{t("close.stopping", { seconds: step.left })}</p>
          {list}
        </>
      )}
      {step.kind === "stuck" && (
        <>
          <p>{t("close.stuck", { count: vms.length })}</p>
          {list}
          <p className="delete-muted">{t("close.powerOffWarning")}</p>
        </>
      )}
    </Dialog>
  );
}
