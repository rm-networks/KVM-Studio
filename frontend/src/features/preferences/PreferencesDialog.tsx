import {
  CircleHelp,
  Disc3,
  FolderTree,
  HardDrive,
  Monitor,
  Settings2,
  SquareTerminal,
} from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, type Config, type IsoLibrary, type IsoLibraryChange } from "../../api/client";
import { Dialog } from "../../components/Dialog";
import { useNotifier } from "../../components/notifier";
import { folderPicker } from "../../platform/folders";
import { openLink } from "../../platform/links";
import { IsoPicker } from "../iso-picker/IsoPicker";
import { ConfirmDialog } from "../vm/ConfirmDialog";
import "./PreferencesDialog.css";

// Stable documentation pages, never a direct link to the ISO itself.
const VIRTIO_WIN_LINKS = [
  {
    key: "fedora",
    url: "https://docs.fedoraproject.org/en-US/quick-docs/creating-windows-virtual-machines-using-virtio-drivers/",
  },
  {
    key: "readme",
    url: "https://github.com/virtio-win/virtio-win-pkg-scripts/blob/master/README.md",
  },
] as const;

type Section = "workspace" | "iso" | "vm" | "interface" | "display" | "advanced";

const SECTIONS: { id: Section; icon: typeof Monitor }[] = [
  { id: "workspace", icon: FolderTree },
  { id: "iso", icon: Disc3 },
  { id: "vm", icon: HardDrive },
  { id: "interface", icon: SquareTerminal },
  { id: "display", icon: Monitor },
  { id: "advanced", icon: Settings2 },
];

function PathField({
  label,
  value,
  placeholder,
  onChange,
}: {
  label: string;
  value: string;
  placeholder?: string;
  onChange: (value: string) => void;
}) {
  const { t } = useTranslation();
  const pick = folderPicker();
  return (
    <label className="prefs-field">
      <span>{label}</span>
      <span className="prefs-path">
        <input
          type="text"
          value={value}
          placeholder={placeholder}
          onChange={(e) => onChange(e.target.value)}
        />
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
    </label>
  );
}

/** Same rule as the backend, before it resolves links: inside a library folder. */
function inIsoLibrary(path: string, libraries: IsoLibrary[]): boolean {
  return libraries.some((lib) => path.startsWith(`${lib.path.replace(/\/+$/, "")}/`));
}

function parentFolder(path: string): string {
  return path.replace(/\/[^/]*$/, "") || "/";
}

function Group({ title, children }: { title: string; children: ReactNode }) {
  return (
    <fieldset className="prefs-group">
      <legend>{title}</legend>
      {children}
    </fieldset>
  );
}

interface Props {
  onClose: () => void;
  /** Called after a save, so the main window picks up theme and language. */
  onSaved: () => void;
}

export function PreferencesDialog({ onClose, onSaved }: Props) {
  const { t } = useTranslation();
  const { notifyError } = useNotifier();
  const [section, setSection] = useState<Section>("workspace");
  const [config, setConfig] = useState<Config | null>(null);
  const [saved, setSaved] = useState<string>("");
  const [libraryRoot, setLibraryRoot] = useState<string | null>(null);
  const [selectedIso, setSelectedIso] = useState(0);
  const [busy, setBusy] = useState(false);
  const [restartPrompt, setRestartPrompt] = useState<Config | null>(null);
  const [declared, setDeclared] = useState<string[] | null>(null);
  const [addingIso, setAddingIso] = useState<{ path: string } | null>(null);
  const [removingIso, setRemovingIso] = useState(false);
  const [pickingVirtio, setPickingVirtio] = useState(false);
  const [virtioHelp, setVirtioHelp] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .preferences()
      .then((prefs) => {
        if (cancelled) return;
        setConfig(prefs.config);
        setSaved(JSON.stringify(prefs.config));
        setLibraryRoot(prefs.library_root);
        setDeclared(prefs.iso_declared ?? null);
      })
      .catch((err: unknown) => !cancelled && notifyError(t("prefs.title"), err));
    return () => {
      cancelled = true;
    };
  }, [notifyError, t]);

  const dirty = config !== null && JSON.stringify(config) !== saved;

  const update = <K extends keyof Config>(key: K, value: Config[K]) =>
    setConfig((c) => (c ? { ...c, [key]: value } : c));

  const updateIso = (index: number, patch: Partial<IsoLibrary>) =>
    config &&
    update(
      "iso_libraries",
      config.iso_libraries.map((lib, i) => (i === index ? { ...lib, ...patch } : lib)),
    );

  const save = async (): Promise<boolean> => {
    if (!config) return false;
    setBusy(true);
    try {
      const result = await api.savePreferences(config);
      setSaved(JSON.stringify(config));
      setLibraryRoot(result.library_root ?? null);
      onSaved();
      if (result.restart_required) setRestartPrompt(config);
      return true;
    } catch (err) {
      notifyError(t("prefs.saveFailed"), err);
      return false;
    } finally {
      setBusy(false);
    }
  };

  const iso = config?.iso_libraries[selectedIso];
  const virtioPath = config?.defaults.virtio_win_iso ?? "";
  const virtioOutside =
    virtioPath.startsWith("/") && !inIsoLibrary(virtioPath, config?.iso_libraries ?? []);

  /** The server saved the library list: take it, keep the other unsaved edits. */
  const applyIsoChange = (change: IsoLibraryChange) => {
    setConfig((c) => (c ? { ...c, iso_libraries: change.config.iso_libraries } : c));
    setSaved((s) => {
      const previous = JSON.parse(s) as Config;
      return JSON.stringify({ ...previous, iso_libraries: change.config.iso_libraries });
    });
    onSaved();
  };

  if (restartPrompt) {
    return <RestartPrompt next={restartPrompt} onClose={onClose} />;
  }

  return (
    <Dialog
      open
      width={720}
      onOpenChange={(open) => !open && onClose()}
      title={t("prefs.title")}
      buttons={
        <>
          <button
            type="button"
            className="button button-primary"
            disabled={!config || busy}
            onClick={() =>
              void (dirty ? save() : Promise.resolve(true)).then((ok) => ok && onClose())
            }
          >
            {t("common.ok")}
          </button>
          <button type="button" className="button" onClick={onClose}>
            {t("common.cancel")}
          </button>
          <button
            type="button"
            className="button"
            disabled={!dirty || busy}
            onClick={() => void save()}
          >
            {t("common.apply")}
          </button>
        </>
      }
    >
      <div className="prefs">
        <ul className="list prefs-sections" role="tablist" aria-orientation="vertical">
          {SECTIONS.map(({ id, icon: Icon }) => (
            <li
              key={id}
              role="tab"
              aria-selected={section === id}
              className="list-row"
              onClick={() => setSection(id)}
            >
              <Icon aria-hidden />
              {t(`prefs.section.${id}`)}
            </li>
          ))}
        </ul>
        <div className="prefs-panel">
          {!config && <p className="prefs-muted">{t("library.loading")}</p>}

          {config && section === "workspace" && (
            <>
              <Group title={t("prefs.vmLocation")}>
                <PathField
                  label={t("prefs.vmLocationLabel")}
                  value={config.storage.vm_default_location ?? ""}
                  placeholder="/srv/vm"
                  onChange={(v) =>
                    update("storage", { ...config.storage, vm_default_location: v || null })
                  }
                />
                <p className="prefs-muted">
                  {libraryRoot
                    ? t("prefs.libraryRoot", { path: libraryRoot })
                    : t("prefs.libraryRootUnset")}
                </p>
              </Group>
            </>
          )}

          {config && section === "iso" && (
            <Group title={t("prefs.isoLibraries")}>
              <p className="prefs-muted">{t("prefs.isoIntro")}</p>
              <ul className="list prefs-list" role="listbox">
                {config.iso_libraries.map((lib, i) => (
                  <li
                    key={i}
                    role="option"
                    aria-selected={i === selectedIso}
                    className="list-row"
                    onClick={() => setSelectedIso(i)}
                  >
                    <span>{lib.name || t("prefs.unnamed")}</span>
                    <span className="muted mono">{lib.path}</span>
                  </li>
                ))}
                {config.iso_libraries.length === 0 && (
                  <li className="list-empty">{t("prefs.noIsoLibrary")}</li>
                )}
              </ul>
              <div className="prefs-list-buttons">
                <button type="button" className="button" onClick={() => setAddingIso({ path: "" })}>
                  {t("prefs.addLibrary")}
                </button>
                <button
                  type="button"
                  className="button"
                  disabled={!iso}
                  onClick={() => setRemovingIso(true)}
                >
                  {t("prefs.removeLibrary")}
                </button>
              </div>
              {iso && (
                <div className="prefs-subform">
                  <label className="prefs-field">
                    <span>{t("prefs.libraryName")}</span>
                    <input
                      type="text"
                      value={iso.name}
                      onChange={(e) => updateIso(selectedIso, { name: e.target.value })}
                    />
                  </label>
                  <div className="prefs-field">
                    <span>{t("prefs.libraryPath")}</span>
                    <span className="prefs-readonly">{iso.path}</span>
                  </div>
                  <label className="prefs-check">
                    <input
                      type="checkbox"
                      checked={iso.recursive ?? true}
                      onChange={(e) => updateIso(selectedIso, { recursive: e.target.checked })}
                    />
                    {t("prefs.recursive")}
                  </label>
                  {declared && !declared.includes(iso.path) && (
                    <p className="prefs-muted">{t("prefs.isoNotDeclared")}</p>
                  )}
                </div>
              )}
            </Group>
          )}

          {config && section === "vm" && (
            <Group title={t("prefs.vmDefaults")}>
              <label className="prefs-field prefs-inline">
                <span>{t("prefs.firmware")}</span>
                <select
                  value={config.defaults.firmware}
                  onChange={(e) =>
                    update("defaults", {
                      ...config.defaults,
                      firmware: e.target.value as Config["defaults"]["firmware"],
                    })
                  }
                >
                  <option value="uefi">UEFI</option>
                  <option value="bios">BIOS</option>
                </select>
              </label>
              <label className="prefs-field prefs-inline">
                <span>{t("prefs.diskBus")}</span>
                <select
                  value={config.defaults.disk_bus}
                  onChange={(e) =>
                    update("defaults", {
                      ...config.defaults,
                      disk_bus: e.target.value as Config["defaults"]["disk_bus"],
                    })
                  }
                >
                  <option value="virtio">VirtIO</option>
                  <option value="scsi">SCSI (virtio-scsi)</option>
                  <option value="sata">SATA</option>
                  <option value="nvme">NVMe</option>
                  <option value="ide">IDE</option>
                </select>
              </label>
              <label className="prefs-field prefs-inline">
                <span>{t("prefs.nicModel")}</span>
                <select
                  value={config.defaults.nic_model}
                  onChange={(e) =>
                    update("defaults", {
                      ...config.defaults,
                      nic_model: e.target.value as Config["defaults"]["nic_model"],
                    })
                  }
                >
                  <option value="virtio">VirtIO</option>
                  <option value="e1000e">Intel e1000e</option>
                  <option value="rtl8139">Realtek RTL8139</option>
                  <option value="vmxnet3">vmxnet3</option>
                </select>
              </label>
              <div className="prefs-field">
                <span className="prefs-label-help">
                  <label htmlFor="prefs-virtio">{t("prefs.virtioWin")}</label>
                  <button
                    type="button"
                    className="icon-button"
                    aria-label={t("prefs.virtioHelpTitle")}
                    title={t("prefs.virtioHelpTitle")}
                    onClick={() => setVirtioHelp(true)}
                  >
                    <CircleHelp aria-hidden />
                  </button>
                </span>
                <span className="prefs-path">
                  <input
                    id="prefs-virtio"
                    type="text"
                    value={config.defaults.virtio_win_iso ?? ""}
                    placeholder="/srv/iso/drivers/virtio-win.iso"
                    onChange={(e) =>
                      update("defaults", {
                        ...config.defaults,
                        virtio_win_iso: e.target.value || null,
                      })
                    }
                  />
                  <button type="button" className="button" onClick={() => setPickingVirtio(true)}>
                    {t("prefs.browse")}
                  </button>
                </span>
              </div>
              {virtioOutside && (
                <div className="note note-warn prefs-note">
                  <p>{t("prefs.virtioOutside")}</p>
                  <button
                    type="button"
                    className="button"
                    onClick={() => setAddingIso({ path: parentFolder(virtioPath) })}
                  >
                    {t("prefs.virtioAddLibrary")}
                  </button>
                </div>
              )}
            </Group>
          )}

          {config && section === "interface" && (
            <Group title={t("prefs.interfaceMode")}>
              <label className="prefs-check">
                <input
                  type="radio"
                  checked={config.interface.mode === "desktop"}
                  onChange={() => update("interface", { mode: "desktop" })}
                />
                {t("prefs.modeDesktop")}
              </label>
              <label className="prefs-check">
                <input
                  type="radio"
                  checked={config.interface.mode === "web"}
                  onChange={() => update("interface", { mode: "web" })}
                />
                {t("prefs.modeWeb")}
              </label>
              <label className="prefs-field prefs-inline prefs-indent">
                <span>{t("prefs.port")}</span>
                <input
                  type="number"
                  min={1024}
                  max={65535}
                  value={config.web.port}
                  onChange={(e) => update("web", { ...config.web, port: Number(e.target.value) })}
                />
              </label>
              <p className="prefs-muted">{t("prefs.appliedOnRestart")}</p>
            </Group>
          )}

          {config && section === "display" && (
            <Group title={t("prefs.appearance")}>
              <label className="prefs-field prefs-inline">
                <span>{t("prefs.theme")}</span>
                <select
                  value={config.ui.theme}
                  onChange={(e) =>
                    update("ui", { ...config.ui, theme: e.target.value as Config["ui"]["theme"] })
                  }
                >
                  <option value="system">{t("prefs.themeSystem")}</option>
                  <option value="light">{t("prefs.themeLight")}</option>
                  <option value="dark">{t("prefs.themeDark")}</option>
                </select>
              </label>
              <label className="prefs-field prefs-inline">
                <span>{t("prefs.language")}</span>
                <select
                  value={config.ui.language}
                  onChange={(e) =>
                    update("ui", {
                      ...config.ui,
                      language: e.target.value as Config["ui"]["language"],
                    })
                  }
                >
                  <option value="system">{t("prefs.languageSystem")}</option>
                  {/* Each language under its own name, whatever the current one. */}
                  <option value="en">English</option>
                  <option value="fr">Français</option>
                </select>
              </label>
            </Group>
          )}

          {config && section === "advanced" && (
            <Group title={t("prefs.libvirt")}>
              <label className="prefs-field">
                <span>{t("prefs.libvirtUri")}</span>
                <input
                  type="text"
                  value={config.libvirt.uri}
                  onChange={(e) => update("libvirt", { uri: e.target.value })}
                />
              </label>
              <p className="prefs-muted">{t("prefs.libvirtHint")}</p>
            </Group>
          )}
        </div>
      </div>
      {addingIso && (
        <AddIsoLibraryDialog
          initialPath={addingIso.path}
          onClose={() => setAddingIso(null)}
          onAdded={(change) => {
            applyIsoChange(change);
            setSelectedIso(change.config.iso_libraries.length - 1);
            const added = change.config.iso_libraries.at(-1)?.path;
            if (change.declared && added) setDeclared((d) => [...(d ?? []), added]);
            setAddingIso(null);
          }}
        />
      )}
      {pickingVirtio && config && (
        <IsoPicker
          title={t("prefs.virtioWin")}
          onPick={(path) => {
            setPickingVirtio(false);
            update("defaults", { ...config.defaults, virtio_win_iso: path });
          }}
          onClose={() => setPickingVirtio(false)}
        />
      )}
      {virtioHelp && (
        <Dialog
          open
          width={480}
          onOpenChange={(open) => !open && setVirtioHelp(false)}
          title={t("prefs.virtioHelpTitle")}
          buttons={
            <button type="button" className="button" onClick={() => setVirtioHelp(false)}>
              {t("common.close")}
            </button>
          }
        >
          <div className="prefs-help">
            <p>{t("prefs.virtioHelp")}</p>
            <p>{t("prefs.virtioDownload")}</p>
            <ul>
              {VIRTIO_WIN_LINKS.map((link) => (
                <li key={link.key}>
                  <a
                    href={link.url}
                    onClick={(e) => {
                      e.preventDefault();
                      openLink(link.url);
                    }}
                  >
                    {t(`prefs.virtioLink.${link.key}`)}
                  </a>
                </li>
              ))}
            </ul>
            <p className="prefs-muted">{t("prefs.virtioNoDownload")}</p>
          </div>
        </Dialog>
      )}
      {removingIso && iso && (
        <ConfirmDialog
          title={t("prefs.removeLibrary")}
          message={t("prefs.removeLibraryConfirm", { name: iso.name, path: iso.path })}
          confirmLabel={t("prefs.removeLibrary")}
          onCancel={() => setRemovingIso(false)}
          onConfirm={() => {
            setRemovingIso(false);
            api
              .removeIsoLibrary(iso.path)
              .then((change) => {
                applyIsoChange(change);
                setSelectedIso(0);
              })
              .catch((err: unknown) => notifyError(t("prefs.removeLibrary"), err));
          }}
        />
      )}
    </Dialog>
  );
}

/** Name and folder of a new library; the helper checks the folder (password asked). */
export function AddIsoLibraryDialog({
  initialPath = "",
  onClose,
  onAdded,
}: {
  initialPath?: string;
  onClose: () => void;
  onAdded: (change: IsoLibraryChange) => void;
}) {
  const { t } = useTranslation();
  const { notifyError } = useNotifier();
  const [name, setName] = useState(t("prefs.newLibrary"));
  const [path, setPath] = useState(initialPath);
  const [recursive, setRecursive] = useState(true);
  const [busy, setBusy] = useState(false);
  const valid = name.trim() !== "" && path.startsWith("/");
  const add = () => {
    setBusy(true);
    api
      .addIsoLibrary({ name: name.trim(), path, recursive })
      .then(onAdded)
      .catch((err: unknown) => {
        notifyError(t("prefs.addLibrary"), err);
        setBusy(false);
      });
  };
  return (
    <Dialog
      open
      width={480}
      onOpenChange={(open) => !open && onClose()}
      title={t("prefs.addLibrary")}
      buttons={
        <>
          <button
            type="button"
            className="button button-primary"
            disabled={!valid || busy}
            onClick={add}
          >
            {t("prefs.addLibrary")}
          </button>
          <button type="button" className="button" onClick={onClose}>
            {t("common.cancel")}
          </button>
        </>
      }
    >
      <div className="prefs-subform">
        <label className="prefs-field">
          <span>{t("prefs.libraryName")}</span>
          <input type="text" value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <PathField label={t("prefs.libraryPath")} value={path} onChange={setPath} />
        <label className="prefs-check">
          <input
            type="checkbox"
            checked={recursive}
            onChange={(e) => setRecursive(e.target.checked)}
          />
          {t("prefs.recursive")}
        </label>
        <p className="prefs-muted">{t("prefs.addLibraryHint")}</p>
      </div>
    </Dialog>
  );
}

export function RestartPrompt({ next, onClose }: { next: Config; onClose: () => void }) {
  const { t } = useTranslation();
  const { notifyError } = useNotifier();
  const [restarting, setRestarting] = useState(false);
  const current = document.documentElement.dataset.mode;
  const toWeb = next.interface.mode === "web" && current !== "web";
  const toDesktop = next.interface.mode === "desktop" && current !== "desktop";

  const message = restarting
    ? toDesktop
      ? t("prefs.restartingToDesktop")
      : t("prefs.restarting")
    : toWeb
      ? t("prefs.restartToWeb", { http: next.web.port })
      : toDesktop
        ? t("prefs.restartToDesktop")
        : t("prefs.restartRequired");

  return (
    <Dialog
      open
      onOpenChange={(open) => !open && !restarting && onClose()}
      title={t("prefs.restartTitle")}
      buttons={
        restarting ? null : (
          <>
            <button
              type="button"
              className="button button-primary"
              onClick={() => {
                setRestarting(true);
                api.restart().catch((err: unknown) => {
                  setRestarting(false);
                  notifyError(t("prefs.restartTitle"), err);
                });
              }}
            >
              {t("prefs.restartNow")}
            </button>
            <button type="button" className="button" onClick={onClose}>
              {t("prefs.restartLater")}
            </button>
          </>
        )
      }
    >
      <p className="prefs-restart">{message}</p>
    </Dialog>
  );
}
