import {
  ArrowDown,
  ArrowUp,
  ClipboardX,
  Cpu,
  Disc3,
  GripVertical,
  HardDrive,
  Info,
  Network as NetworkIcon,
  Power,
  TriangleAlert,
} from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { VmOptions } from "../../api/client";
import { PROFILE_IDS, type OptionsDraft, risky, sameBoot } from "./optionsDraft";

type Pane = "general" | "power" | "boot" | "isolation";

const PANES: { id: Pane; icon: typeof Cpu }[] = [
  { id: "general", icon: Info },
  { id: "power", icon: Power },
  { id: "boot", icon: Cpu },
  { id: "isolation", icon: ClipboardX },
];

const DEVICE_ICON = { disk: HardDrive, cdrom: Disc3, nic: NetworkIcon } as const;

interface Props {
  options: VmOptions;
  draft: OptionsDraft;
  onChange: (draft: OptionsDraft) => void;
}

export function OptionsTab({ options, draft, onChange }: Props) {
  const { t } = useTranslation();
  const [pane, setPane] = useState<Pane>("general");
  const [dragged, setDragged] = useState<number | null>(null);
  const set = (patch: Partial<OptionsDraft>) => onChange({ ...draft, ...patch });
  const off = !options.active;

  const move = (from: number, to: number) => {
    if (to < 0 || to >= draft.boot.length || from === to) return;
    const boot = [...draft.boot];
    const [item] = boot.splice(from, 1);
    if (item) boot.splice(to, 0, item);
    set({ boot });
  };

  const offNote = !off && (
    <p className="note">
      <Info aria-hidden />
      <span>{t("options.needsOff")}</span>
    </p>
  );
  const nextStartNote = !off && (
    <p className="note">
      <Info aria-hidden />
      <span>{t("options.nextStart")}</span>
    </p>
  );

  return (
    <div className="settings">
      <div className="settings-left">
        <div className="list settings-devices">
          <div className="settings-device settings-device-header" aria-hidden>
            <span>{t("options.setting")}</span>
            <span>{t("settings.summary")}</span>
          </div>
          <ul role="listbox" aria-label={t("options.setting")}>
            {PANES.map(({ id, icon: Icon }) => (
              <li
                key={id}
                role="option"
                aria-selected={pane === id}
                className="list-row settings-device"
                onClick={() => setPane(id)}
              >
                <span className="settings-device-name">
                  <Icon aria-hidden />
                  {t(`options.pane.${id}`)}
                </span>
                <span className="muted">{summary(id)}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      <div className="settings-panel">
        {pane === "general" && (
          <fieldset className="group">
            <legend>{t("options.pane.general")}</legend>
            {offNote}
            <label className="settings-inline">
              {t("options.name")}
              <input
                type="text"
                value={draft.name}
                disabled={!off}
                onChange={(e) => set({ name: e.target.value })}
              />
            </label>
            <label className="settings-inline">
              {t("options.os")}
              <select
                value={draft.profile ?? ""}
                onChange={(e) => set({ profile: e.target.value || null })}
              >
                {draft.profile === null && <option value="">-</option>}
                {PROFILE_IDS.map((id) => (
                  <option key={id} value={id}>
                    {t(`wizard.profile.${id}`)}
                  </option>
                ))}
              </select>
            </label>
            <p className="muted">{t("options.osHint")}</p>
          </fieldset>
        )}

        {pane === "power" && (
          <fieldset className="group">
            <legend>{t("options.pane.power")}</legend>
            <label className="check">
              <input
                type="checkbox"
                checked={draft.autostart}
                onChange={(e) => set({ autostart: e.target.checked })}
              />
              {t("options.autostart")}
            </label>
            <label className="settings-inline">
              {t("options.onReboot")}
              <select value={draft.on_reboot} onChange={(e) => set({ on_reboot: e.target.value })}>
                <option value="restart">{t("options.action.restart")}</option>
                <option value="destroy">{t("options.action.destroy")}</option>
              </select>
            </label>
            <label className="settings-inline">
              {t("options.onCrash")}
              <select value={draft.on_crash} onChange={(e) => set({ on_crash: e.target.value })}>
                <option value="destroy">{t("options.action.destroy")}</option>
                <option value="restart">{t("options.action.restart")}</option>
                <option value="preserve">{t("options.action.preserve")}</option>
              </select>
            </label>
            {draft.on_reboot !== options.on_reboot || draft.on_crash !== options.on_crash
              ? nextStartNote
              : null}
          </fieldset>
        )}

        {pane === "boot" && (
          <>
            <fieldset className="group">
              <legend>{t("options.firmware")}</legend>
              {offNote}
              <label className="check">
                <input
                  type="radio"
                  name="firmware"
                  checked={draft.firmware === "uefi"}
                  disabled={!off}
                  onChange={() => set({ firmware: "uefi" })}
                />
                UEFI
              </label>
              <label className="check">
                <input
                  type="radio"
                  name="firmware"
                  checked={draft.firmware === "bios"}
                  disabled={!off}
                  onChange={() => set({ firmware: "bios", secure_boot: false })}
                />
                BIOS
              </label>
              <label className="check">
                <input
                  type="checkbox"
                  checked={draft.firmware === "uefi" && draft.secure_boot}
                  disabled={!off || draft.firmware !== "uefi"}
                  onChange={(e) => set({ secure_boot: e.target.checked })}
                />
                {t("options.secureBoot")}
              </label>
              <label className="check">
                <input
                  type="checkbox"
                  checked={draft.tpm}
                  disabled={!off}
                  onChange={(e) => set({ tpm: e.target.checked })}
                />
                {t("options.tpm")}
              </label>
              {risky(options, draft) && (
                <p className="note note-warn">
                  <TriangleAlert aria-hidden />
                  <span>{t("options.riskyNote")}</span>
                </p>
              )}
              {(options.reset_nvram_pending ||
                (draft.firmware === "uefi" && draft.secure_boot !== options.secure_boot)) && (
                <p className="muted">{t("options.nvramReset")}</p>
              )}
            </fieldset>
            <fieldset className="group">
              <legend>{t("options.bootOrder")}</legend>
              <p className="muted">{t("options.bootOrderHint")}</p>
              <ul className="list boot-order" aria-label={t("options.bootOrder")}>
                {draft.boot.map((dev, i) => {
                  const Icon = DEVICE_ICON[dev.kind];
                  const label = t(`options.device.${dev.kind}`, { id: dev.id });
                  return (
                    <li
                      key={`${dev.kind}:${dev.id}`}
                      className="list-row boot-order-row"
                      draggable
                      data-dragging={dragged === i}
                      onDragStart={(e) => {
                        setDragged(i);
                        e.dataTransfer.effectAllowed = "move";
                      }}
                      onDragOver={(e) => e.preventDefault()}
                      onDrop={(e) => {
                        e.preventDefault();
                        if (dragged !== null) move(dragged, i);
                        setDragged(null);
                      }}
                      onDragEnd={() => setDragged(null)}
                    >
                      <GripVertical aria-hidden className="boot-order-grip" />
                      <input
                        type="checkbox"
                        aria-label={label}
                        checked={dev.enabled}
                        onChange={(e) =>
                          set({
                            boot: draft.boot.map((d, j) =>
                              j === i ? { ...d, enabled: e.target.checked } : d,
                            ),
                          })
                        }
                      />
                      <Icon aria-hidden />
                      <span className="boot-order-label">
                        {label}
                        {dev.detail && <span className="muted"> {dev.detail}</span>}
                      </span>
                      <button
                        type="button"
                        className="icon-button"
                        aria-label={t("options.up", { device: label })}
                        title={t("options.upShort")}
                        disabled={i === 0}
                        onClick={() => move(i, i - 1)}
                      >
                        <ArrowUp />
                      </button>
                      <button
                        type="button"
                        className="icon-button"
                        aria-label={t("options.down", { device: label })}
                        title={t("options.downShort")}
                        disabled={i === draft.boot.length - 1}
                        onClick={() => move(i, i + 1)}
                      >
                        <ArrowDown />
                      </button>
                    </li>
                  );
                })}
              </ul>
              {!draft.boot.some((d) => d.enabled) && (
                <p className="field-error">{t("options.noBootDevice")}</p>
              )}
              <label className="check">
                <input
                  type="checkbox"
                  checked={draft.boot_menu}
                  onChange={(e) => set({ boot_menu: e.target.checked })}
                />
                {t("options.bootMenu")}
              </label>
              {(!sameBoot(draft.boot, options.boot) || draft.boot_menu !== options.boot_menu) &&
                nextStartNote}
            </fieldset>
          </>
        )}

        {pane === "isolation" && (
          <fieldset className="group">
            <legend>{t("options.pane.isolation")}</legend>
            <label className="check">
              <input
                type="checkbox"
                checked={draft.clipboard}
                onChange={(e) => set({ clipboard: e.target.checked })}
              />
              {t("options.clipboard")}
            </label>
            <p className="muted">{t("options.clipboardHint")}</p>
            {draft.clipboard !== options.clipboard && nextStartNote}
          </fieldset>
        )}
      </div>
    </div>
  );

  function summary(id: Pane): string {
    switch (id) {
      case "general":
        return draft.profile ? t(`wizard.profile.${draft.profile}`) : "";
      case "power":
        return draft.autostart ? t("options.autostartShort") : "";
      case "boot":
        return draft.firmware === "uefi"
          ? draft.secure_boot
            ? t("options.uefiSecure")
            : "UEFI"
          : "BIOS";
      case "isolation":
        return draft.clipboard ? t("options.clipboardOn") : t("options.clipboardOff");
    }
  }
}
