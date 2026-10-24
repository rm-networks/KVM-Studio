import { CheckCircle2, LoaderCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, type GuestToolsInfo, type InstallRequest, type VmSummary } from "../../api/client";
import { Dialog } from "../../components/Dialog";
import { useNotifier } from "../../components/notifier";
import "./GuestToolsDialog.css";

type Family = InstallRequest["family"];
type Layout = InstallRequest["layout"];
type Phase = "form" | "waiting" | "done" | "timeout";

const POLL_MS = 5000;
const WAIT_MS = 10 * 60 * 1000;

export function GuestToolsDialog({ vm, onClose }: { vm: VmSummary; onClose: () => void }) {
  const { t } = useTranslation();
  const { notifyError } = useNotifier();
  const [info, setInfo] = useState<GuestToolsInfo | null>(null);
  const [family, setFamily] = useState<Family>("linux");
  const [layout, setLayout] = useState<Layout>("fr");
  const [phase, setPhase] = useState<Phase>("form");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    api
      .guestTools(vm.uuid)
      .then((value) => {
        if (!live) return;
        setInfo(value);
        if (value.family === "windows" || value.family === "linux") setFamily(value.family);
        if (value.layout) setLayout(value.layout);
      })
      .catch((err: unknown) => notifyError(t("guestTools.failed"), err));
    return () => {
      live = false;
    };
  }, [vm.uuid, notifyError, t]);

  useEffect(() => {
    if (phase !== "waiting") return;
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
  }, [phase, vm.uuid]);

  const running = vm.state === "running";
  const missingIso = family === "windows" && !info?.virtio_win;
  const canInstall = info !== null && running && !missingIso && !busy && phase === "form";

  const install = () => {
    setBusy(true);
    api
      .installGuestTools(vm.uuid, { family, layout })
      .then(() => setPhase("waiting"))
      .catch((err: unknown) => notifyError(t("guestTools.failed"), err))
      .finally(() => setBusy(false));
  };

  return (
    <Dialog
      open
      onOpenChange={(open) => !open && onClose()}
      title={t("guestTools.title", { name: vm.name })}
      width={480}
      buttons={
        phase === "form" ? (
          <>
            <button
              type="button"
              className="button button-primary"
              disabled={!canInstall}
              onClick={install}
            >
              {t("guestTools.install")}
            </button>
            <button type="button" className="button" onClick={onClose}>
              {t("common.cancel")}
            </button>
          </>
        ) : (
          <button type="button" className="button" onClick={onClose}>
            {t("common.close")}
          </button>
        )
      }
    >
      {phase === "form" && (
        <div className="guest-tools">
          {info?.agent && <p className="guest-tools-ok">{t("guestTools.alreadyOk")}</p>}
          {!running && <p className="field-error">{t("guestTools.mustRun")}</p>}
          <label className="field">
            <span>{t("guestTools.family")}</span>
            <select value={family} onChange={(e) => setFamily(e.target.value as Family)}>
              <option value="windows">Windows</option>
              <option value="linux">Linux</option>
            </select>
          </label>
          <label className="field">
            <span>{t("guestTools.layout")}</span>
            <select value={layout} onChange={(e) => setLayout(e.target.value as Layout)}>
              <option value="fr">{t("guestTools.layoutFr")}</option>
              <option value="us">{t("guestTools.layoutUs")}</option>
            </select>
          </label>
          <p className="guest-tools-help">
            {family === "windows" ? t("guestTools.helpWindows") : t("guestTools.helpLinux")}
          </p>
          {family === "windows" &&
            (info?.virtio_win ? (
              <p className="guest-tools-path">{info.virtio_win}</p>
            ) : (
              <p className="field-error">{t("guestTools.noVirtio")}</p>
            ))}
        </div>
      )}
      {phase === "waiting" && (
        <p className="guest-tools-status">
          <LoaderCircle size={16} className="spin" aria-hidden />
          {family === "windows" ? t("guestTools.waitWindows") : t("guestTools.waitLinux")}
        </p>
      )}
      {phase === "done" && (
        <p className="guest-tools-status">
          <CheckCircle2 size={16} aria-hidden />
          {t("guestTools.done")}
        </p>
      )}
      {phase === "timeout" && <p className="field-error">{t("guestTools.timeout")}</p>}
    </Dialog>
  );
}
