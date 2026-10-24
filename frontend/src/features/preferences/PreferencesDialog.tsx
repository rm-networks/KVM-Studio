import { Disc3, FolderTree, HardDrive, Monitor, Settings2, SquareTerminal } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, type Config, type IsoLibrary } from "../../api/client";
import { Dialog } from "../../components/Dialog";
import { useNotifier } from "../../components/notifier";
import { folderPicker } from "../../platform/folders";
import "./PreferencesDialog.css";

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
  const { notify, notifyError } = useNotifier();
  const [section, setSection] = useState<Section>("workspace");
  const [config, setConfig] = useState<Config | null>(null);
  const [saved, setSaved] = useState<string>("");
  const [libraryRoot, setLibraryRoot] = useState<string | null>(null);
  const [selectedIso, setSelectedIso] = useState(0);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .preferences()
      .then((prefs) => {
        if (cancelled) return;
        setConfig(prefs.config);
        setSaved(JSON.stringify(prefs.config));
        setLibraryRoot(prefs.library_root);
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
      if (result.restart_required) notify(t("prefs.saved"), t("prefs.restartRequired"));
      return true;
    } catch (err) {
      notifyError(t("prefs.saveFailed"), err);
      return false;
    } finally {
      setBusy(false);
    }
  };

  const iso = config?.iso_libraries[selectedIso];

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
        <ul className="prefs-sections" role="tablist" aria-orientation="vertical">
          {SECTIONS.map(({ id, icon: Icon }) => (
            <li
              key={id}
              role="tab"
              aria-selected={section === id}
              className={section === id ? "selected" : undefined}
              onClick={() => setSection(id)}
            >
              <Icon size={14} strokeWidth={1.75} aria-hidden />
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
              <Group title={t("prefs.isoFolder")}>
                <PathField
                  label={t("prefs.isoFolderLabel")}
                  value={config.storage.default_iso_folder ?? ""}
                  onChange={(v) =>
                    update("storage", { ...config.storage, default_iso_folder: v || null })
                  }
                />
              </Group>
            </>
          )}

          {config && section === "iso" && (
            <Group title={t("prefs.isoLibraries")}>
              <p className="prefs-muted">{t("prefs.isoIntro")}</p>
              <ul className="prefs-list" role="listbox">
                {config.iso_libraries.map((lib, i) => (
                  <li
                    key={i}
                    role="option"
                    aria-selected={i === selectedIso}
                    className={i === selectedIso ? "selected" : undefined}
                    onClick={() => setSelectedIso(i)}
                  >
                    <strong>{lib.name || t("prefs.unnamed")}</strong>
                    <span>{lib.path}</span>
                  </li>
                ))}
                {config.iso_libraries.length === 0 && (
                  <li className="prefs-muted">{t("prefs.noIsoLibrary")}</li>
                )}
              </ul>
              <div className="prefs-list-buttons">
                <button
                  type="button"
                  className="button"
                  onClick={() => {
                    update("iso_libraries", [
                      ...config.iso_libraries,
                      { name: t("prefs.newLibrary"), path: "", recursive: true },
                    ]);
                    setSelectedIso(config.iso_libraries.length);
                  }}
                >
                  {t("prefs.addLibrary")}
                </button>
                <button
                  type="button"
                  className="button"
                  disabled={!iso}
                  onClick={() => {
                    update(
                      "iso_libraries",
                      config.iso_libraries.filter((_l, i) => i !== selectedIso),
                    );
                    setSelectedIso(0);
                  }}
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
                  <PathField
                    label={t("prefs.libraryPath")}
                    value={iso.path}
                    onChange={(v) => updateIso(selectedIso, { path: v })}
                  />
                  <label className="prefs-check">
                    <input
                      type="checkbox"
                      checked={iso.recursive ?? true}
                      onChange={(e) => updateIso(selectedIso, { recursive: e.target.checked })}
                    />
                    {t("prefs.recursive")}
                  </label>
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
              <label className="prefs-field">
                <span>{t("prefs.virtioWin")}</span>
                <input
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
              </label>
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
                  disabled={config.interface.mode !== "web"}
                  onChange={(e) => update("web", { ...config.web, port: Number(e.target.value) })}
                />
              </label>
              <label className="prefs-check prefs-indent" title={t("networks.bridgedLater")}>
                <input type="checkbox" checked={false} disabled />
                <span className="prefs-disabled">{t("prefs.shareLan")}</span>
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
                  <option value="fr">Français</option>
                  <option value="en">English</option>
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
    </Dialog>
  );
}
