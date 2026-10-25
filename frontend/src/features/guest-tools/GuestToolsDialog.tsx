import { CircleCheck, Copy, LoaderCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, type GuestFamily, type GuestToolsInfo, type VmSummary } from "../../api/client";
import { Dialog } from "../../components/Dialog";
import { useNotifier } from "../../components/notifier";
import { hostClipboard } from "../../platform/hostClipboard";
import "./GuestToolsDialog.css";

type Phase = "form" | "waiting" | "done" | "timeout";

const POLL_MS = 5000;
const WAIT_MS = 10 * 60 * 1000;

export function GuestToolsDialog({ vm, onClose }: { vm: VmSummary; onClose: () => void }) {
  const { t } = useTranslation();
  const { notifyError } = useNotifier();
  const [info, setInfo] = useState<GuestToolsInfo | null>(null);
  const [family, setFamily] = useState<GuestFamily>("linux");
  const [phase, setPhase] = useState<Phase>("form");
  const [restart, setRestart] = useState(false);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let live = true;
    api
      .guestTools(vm.uuid)
      .then((value) => {
        if (!live) return;
        setInfo(value);
        if (value.family) setFamily(value.family);
        if (value.inserted) setPhase("waiting");
      })
      .catch((err: unknown) => notifyError(t("guestTools.failed"), err));
    return () => {
      live = false;
    };
  }, [vm.uuid, notifyError, t]);

  const running = vm.state === "running";

  useEffect(() => {
    if (phase !== "waiting" || !running) return;
    const started = Date.now();
    const timer = window.setInterval(() => {
      api
        .agentStatus(vm.uuid)
        .then(({ responding }) => {
          if (responding) setPhase("done");
          else if (Date.now() - started > WAIT_MS) setPhase("timeout");
        })
        .catch(() => undefined);
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [phase, running, vm.uuid]);

  const supported = family === "windows" || family === "linux";
  const missingIso = family === "windows" && !info?.virtio_win;
  const canInsert = info !== null && supported && !missingIso && !busy;

  const insert = () => {
    setBusy(true);
    api
      .insertGuestTools(vm.uuid, family)
      .then((result) => {
        setRestart(result.restart_required);
        setPhase("waiting");
      })
      .catch((err: unknown) => notifyError(t("guestTools.failed"), err))
      .finally(() => setBusy(false));
  };

  const eject = () => {
    setBusy(true);
    api
      .ejectGuestTools(vm.uuid)
      .then(onClose)
      .catch((err: unknown) => notifyError(t("guestTools.ejectFailed"), err))
      .finally(() => setBusy(false));
  };

  const copyCommand = () => {
    if (!info) return;
    void hostClipboard.write(info.linux_command).then(() => setCopied(true));
  };

  const step = (done: boolean, text: string, pending = false) => (
    <li className={done ? "guest-tools-step done" : "guest-tools-step"}>
      {done ? (
        <CircleCheck aria-hidden />
      ) : pending ? (
        <LoaderCircle className="spin" aria-hidden />
      ) : (
        <span className="guest-tools-dot" />
      )}
      <span>{text}</span>
    </li>
  );

  return (
    <Dialog
      open
      onOpenChange={(open) => !open && onClose()}
      title={t("guestTools.title", { name: vm.name })}
      width={520}
      buttons={
        phase === "form" ? (
          <>
            <button
              type="button"
              className="button button-primary"
              disabled={!canInsert}
              onClick={insert}
            >
              {t("guestTools.insert")}
            </button>
            <button type="button" className="button" onClick={onClose}>
              {t("common.cancel")}
            </button>
          </>
        ) : (
          <>
            <button
              type="button"
              className={phase === "done" ? "button button-primary" : "button"}
              disabled={busy}
              onClick={eject}
            >
              {t("guestTools.eject")}
            </button>
            <button type="button" className="button" onClick={onClose}>
              {t("common.close")}
            </button>
          </>
        )
      }
    >
      <div className="guest-tools">
        {phase === "form" && (
          <>
            {info?.agent && <p className="guest-tools-ok">{t("guestTools.alreadyOk")}</p>}
            <p>{t("guestTools.intro")}</p>
            <label className="field">
              <span>{t("guestTools.family")}</span>
              <select value={family} onChange={(e) => setFamily(e.target.value as GuestFamily)}>
                <option value="windows">Windows</option>
                <option value="linux">Linux</option>
              </select>
            </label>
            {!supported && <p className="field-error">{t("guestTools.unsupported")}</p>}
            {family === "windows" &&
              (info?.virtio_win ? (
                <p className="guest-tools-path">{info.virtio_win}</p>
              ) : (
                <p className="field-error">{t("guestTools.noVirtio")}</p>
              ))}
          </>
        )}

        {phase !== "form" && (
          <>
            <ol className="guest-tools-steps">
              {step(true, `1. ${t("guestTools.step.inserted")}`)}
              {step(phase === "done", `2. ${t("guestTools.step.run")}`)}
              {step(
                phase === "done",
                `3. ${t(phase === "done" ? "guestTools.step.done" : "guestTools.step.wait")}`,
                phase === "waiting" && running,
              )}
            </ol>
            {phase !== "done" &&
              (family === "linux" && info ? (
                <>
                  <p className="guest-tools-help">{t("guestTools.linuxHow")}</p>
                  <div className="guest-tools-command">
                    <code>{info.linux_command}</code>
                    <button type="button" className="button" onClick={copyCommand}>
                      <Copy aria-hidden /> {copied ? t("guestTools.copied") : t("guestTools.copy")}
                    </button>
                  </div>
                </>
              ) : (
                <p className="guest-tools-help">{t("guestTools.windowsHow")}</p>
              ))}
            {restart && <p className="field-error">{t("guestTools.restart")}</p>}
            {!running && phase === "waiting" && (
              <p className="guest-tools-path">{t("guestTools.notRunning")}</p>
            )}
            {phase === "timeout" && <p className="field-error">{t("guestTools.timeout")}</p>}
          </>
        )}
      </div>
    </Dialog>
  );
}
