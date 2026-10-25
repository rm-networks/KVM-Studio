import { CircleCheck, Copy, LoaderCircle, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  api,
  type GuestFamily,
  type GuestToolsInfo,
  type InsertResult,
  type VmSummary,
} from "../../api/client";
import { Dialog } from "../../components/Dialog";
import { useNotifier } from "../../components/notifier";
import { hostClipboard } from "../../platform/hostClipboard";
import { AddIsoLibraryDialog } from "../preferences/PreferencesDialog";
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
  const [result, setResult] = useState<InsertResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [addingLibrary, setAddingLibrary] = useState(false);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let live = true;
    api
      .guestTools(vm.uuid)
      .then((value) => {
        if (!live) return;
        setInfo(value);
        // A reload (library added) keeps what the user chose.
        if (reload) return;
        if (value.family) setFamily(value.family);
        if (value.inserted) setPhase("waiting");
      })
      .catch((err: unknown) => notifyError(t("guestTools.failed"), err));
    return () => {
      live = false;
    };
  }, [vm.uuid, notifyError, t, reload]);

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
  const virtioState = info?.virtio_state ?? "unset";
  const missingIso = family === "windows" && virtioState !== "ok";
  const canInsert = info !== null && supported && !missingIso && !busy;
  const restart = result?.restart_required ?? false;
  const virtioFolder = info?.virtio_win?.replace(/\/[^/]*$/, "") || "/";

  const insert = () => {
    setBusy(true);
    api
      .insertGuestTools(vm.uuid, family)
      .then((value) => {
        setResult(value);
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

  type StepState = "done" | "pending" | "warn" | "todo";
  const step = (state: StepState, text: string) => (
    <li key={text} className={`guest-tools-step ${state}`}>
      {state === "done" ? (
        <CircleCheck aria-hidden />
      ) : state === "pending" ? (
        <LoaderCircle className="spin" aria-hidden />
      ) : state === "warn" ? (
        <TriangleAlert aria-hidden />
      ) : (
        <span className="guest-tools-dot" />
      )}
      <span>{text}</span>
    </li>
  );

  const done = phase === "done";
  // Reopened while the CD is in: the drive and installer are not known any more.
  const steps: [StepState, string][] = [];
  if (result?.installer) {
    steps.push(["done", t("guestTools.step.installer", { name: result.installer })]);
  }
  steps.push(
    result
      ? restart
        ? ["warn", t("guestTools.step.insertedRestart", { drive: result.drive })]
        : ["done", t("guestTools.step.insertedIn", { drive: result.drive })]
      : ["done", t("guestTools.step.inserted")],
  );
  steps.push([done ? "done" : "todo", t("guestTools.step.run")]);
  steps.push(
    done
      ? ["done", t("guestTools.step.done")]
      : [
          phase === "waiting" && running && !restart ? "pending" : "todo",
          t("guestTools.step.wait"),
        ],
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
            {family === "windows" && info && (
              <>
                <p className="guest-tools-help">{t("guestTools.windowsIntro")}</p>
                {info.virtio_win && <p className="guest-tools-path">{info.virtio_win}</p>}
                {virtioState !== "ok" && (
                  <p className="field-error">{t(`guestTools.virtio.${virtioState}`)}</p>
                )}
                {virtioState === "outside" && (
                  <p>
                    <button type="button" className="button" onClick={() => setAddingLibrary(true)}>
                      {t("guestTools.addLibrary")}
                    </button>
                  </p>
                )}
              </>
            )}
          </>
        )}

        {phase !== "form" && (
          <>
            <ol className="guest-tools-steps">
              {steps.map(([state, text], i) => step(state, `${i + 1}. ${text}`))}
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
            {restart && !done && <p className="field-error">{t("guestTools.restart")}</p>}
            {!running && phase === "waiting" && (
              <p className="guest-tools-path">{t("guestTools.notRunning")}</p>
            )}
            {phase === "timeout" && <p className="field-error">{t("guestTools.timeout")}</p>}
          </>
        )}
      </div>
      {addingLibrary && (
        <AddIsoLibraryDialog
          initialPath={virtioFolder}
          onClose={() => setAddingLibrary(false)}
          onAdded={() => {
            setAddingLibrary(false);
            setReload((n) => n + 1);
          }}
        />
      )}
    </Dialog>
  );
}
