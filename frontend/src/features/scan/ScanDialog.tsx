import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api, type FoundVm, type ScanChoice } from "../../api/client";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Dialog } from "../../components/Dialog";
import { useNotifier } from "../../components/notifier";
import { BrowseButton } from "../files/BrowseButton";
import "./ScanDialog.css";

type Mode = NonNullable<ScanChoice["mode"]>;
const MODES: Mode[] = ["keep", "copy", "move"];

interface Props {
  /** Where to start: the VM location, as a rule. */
  start: string | null;
  onClose: () => void;
}

/** File > Scan for Virtual Machines: VMs found in a folder tree, imported on demand. */
export function ScanDialog({ start, onClose }: Props) {
  const { t } = useTranslation();
  const { notify, notifyError } = useNotifier();
  const [path, setPath] = useState(start ?? "");
  const [found, setFound] = useState<FoundVm[] | null>(null);
  const [scanned, setScanned] = useState("");
  const [busy, setBusy] = useState(false);
  const [picked, setPicked] = useState<Record<string, Mode>>({});
  const [moves, setMoves] = useState<[string, string][] | null>(null);

  const choices = (): ScanChoice[] => Object.entries(picked).map(([id, mode]) => ({ id, mode }));

  const runScan = () => {
    const where = path.trim();
    setBusy(true);
    api
      .scan(where)
      .then((items) => {
        setFound(items);
        setScanned(where);
        // What libvirt does not know yet is picked, its files left where they are.
        setPicked(
          Object.fromEntries(items.filter((i) => !i.known).map((i) => [i.id, "keep" as Mode])),
        );
      })
      .catch((err: unknown) => notifyError(t("scan.title"), err))
      .finally(() => setBusy(false));
  };

  const importNow = () =>
    api.scanImport(scanned, choices()).then((result) => {
      if (result.imported.length) {
        notify(t("scan.imported", { count: result.imported.length }), result.imported.join(", "));
      }
      for (const failure of result.failed) {
        notify(t("scan.failed", { name: failure.name }), failure.error);
      }
      onClose();
    });

  const startImport = () => {
    if (!Object.values(picked).some((mode) => mode !== "keep")) {
      setBusy(true);
      importNow().catch((err: unknown) => {
        setBusy(false);
        notifyError(t("scan.title"), err);
      });
      return;
    }
    api
      .scanPlan(scanned, choices())
      .then((plan) => setMoves(plan.moves))
      .catch((err: unknown) => notifyError(t("scan.title"), err));
  };

  const count = Object.keys(picked).length;

  return (
    <>
      <Dialog
        open
        width={820}
        onOpenChange={(o) => !o && !busy && onClose()}
        title={t("scan.title")}
        buttons={
          <>
            <button
              type="button"
              className="button button-primary"
              disabled={busy || count === 0 || found === null}
              onClick={startImport}
            >
              {t("scan.import", { count })}
            </button>
            <button type="button" className="button" disabled={busy} onClick={onClose}>
              {t("common.cancel")}
            </button>
          </>
        }
      >
        <p>{t("scan.intro")}</p>
        <div className="row scan-path">
          <input
            type="text"
            value={path}
            aria-label={t("scan.folder")}
            placeholder="/…"
            onChange={(e) => setPath(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && path.trim() && runScan()}
          />
          <BrowseButton
            kind="folder"
            start={path.trim() || null}
            title={t("scan.folder")}
            onPick={setPath}
          />
          <button
            type="button"
            className="button"
            disabled={busy || !path.trim()}
            onClick={runScan}
          >
            {busy && found === null ? t("scan.scanning") : t("scan.scan")}
          </button>
        </div>
        {found !== null && found.length === 0 && <p className="muted">{t("scan.none")}</p>}
        {found !== null && found.length > 0 && (
          <div className="list scan-results">
            <table className="table">
              <thead>
                <tr>
                  <th />
                  <th>{t("scan.name")}</th>
                  <th>{t("scan.libraryFolder")}</th>
                  <th>{t("scan.disks")}</th>
                  <th>{t("scan.files")}</th>
                </tr>
              </thead>
              <tbody>
                {found.map((item) => {
                  const mode = picked[item.id];
                  return (
                    <tr key={item.id} className={item.known ? "scan-known" : undefined}>
                      <td>
                        <input
                          type="checkbox"
                          aria-label={item.name}
                          checked={mode !== undefined}
                          disabled={item.known !== null}
                          onChange={(e) =>
                            setPicked((all) =>
                              e.target.checked
                                ? { ...all, [item.id]: "keep" }
                                : Object.fromEntries(
                                    Object.entries(all).filter(([id]) => id !== item.id),
                                  ),
                            )
                          }
                        />
                      </td>
                      <td>
                        {item.name}
                        {item.known && (
                          <span className="scan-note">{t("scan.known", { name: item.known })}</span>
                        )}
                        {item.definition && !item.known && (
                          <span className="scan-note">{t("scan.definition")}</span>
                        )}
                      </td>
                      <td>{item.folder || t("library.myComputer")}</td>
                      <td className="mono" title={item.disks.join("\n")}>
                        {item.disks.map((d) => d.slice(d.lastIndexOf("/") + 1)).join(", ")}
                      </td>
                      <td>
                        <select
                          aria-label={t("scan.files")}
                          value={mode ?? "keep"}
                          disabled={mode === undefined}
                          onChange={(e) =>
                            setPicked((all) => ({ ...all, [item.id]: e.target.value as Mode }))
                          }
                        >
                          {MODES.map((m) => (
                            <option key={m} value={m}>
                              {t(`scan.mode.${m}`)}
                            </option>
                          ))}
                        </select>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Dialog>
      {moves && (
        <ConfirmDialog
          title={t("scan.confirmTitle")}
          confirmLabel={t("scan.confirm")}
          busyLabel={t("library.copying")}
          onConfirm={importNow}
          onClose={() => setMoves(null)}
        >
          <p>{t("scan.confirmIntro")}</p>
          <ul className="move-list mono">
            {moves.map(([from, to]) => (
              <li key={from}>
                {from} → {to}
              </li>
            ))}
          </ul>
        </ConfirmDialog>
      )}
    </>
  );
}
