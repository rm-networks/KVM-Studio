import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import {
  Cpu,
  Disc3,
  HardDrive,
  MemoryStick,
  Network as NetworkIcon,
  TriangleAlert,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  api,
  type Hardware,
  type HardwareNic,
  type HostCapabilities,
  type Network,
  type NicChange,
  type VmOptions,
  type VmSummary,
} from "../../api/client";
import { Dialog } from "../../components/Dialog";
import { useNotifier } from "../../components/notifier";
import { IsoPicker } from "../iso-picker/IsoPicker";
import { ConfirmDialog } from "../vm/ConfirmDialog";
import { OptionsTab } from "./OptionsTab";
import { type OptionsDraft, draftOf, optionsChange, risky } from "./optionsDraft";
import { DiskPanel } from "./DiskPanel";
import "./VmSettings.css";

type Selection =
  | { kind: "memory" }
  | { kind: "cpu" }
  | { kind: "disk"; target: string }
  | { kind: "cdrom"; target: string }
  | { kind: "nic"; mac: string };

interface NicEdit {
  network: string | null;
  model: string;
  connected: boolean;
}

function fileName(path: string | null): string | null {
  return path ? path.slice(path.lastIndexOf("/") + 1) : null;
}

export function VmSettings({ vm, onClose }: { vm: VmSummary; onClose: () => void }) {
  const { t } = useTranslation();
  const { notify, notifyError } = useNotifier();
  const [hw, setHw] = useState<Hardware | null>(null);
  const [host, setHost] = useState<HostCapabilities | null>(null);
  const [networks, setNetworks] = useState<Network[]>([]);
  const [selection, setSelection] = useState<Selection>({ kind: "memory" });
  const [memory, setMemory] = useState(0);
  const [vcpus, setVcpus] = useState(0);
  const [nicEdits, setNicEdits] = useState<Record<string, NicEdit>>({});
  const [busy, setBusy] = useState(false);
  const [picking, setPicking] = useState<string | null>(null);
  const [removing, setRemoving] = useState<Selection | null>(null);
  const [tab, setTab] = useState<"hardware" | "options">("hardware");
  const [opts, setOpts] = useState<VmOptions | null>(null);
  const [optDraft, setOptDraft] = useState<OptionsDraft | null>(null);
  // Risky firmware or TPM change waiting for a confirmation; close: from OK.
  const [confirmRisky, setConfirmRisky] = useState<{ close: boolean } | null>(null);

  const receive = useCallback((data: Hardware) => {
    setHw(data);
    setMemory(data.memory_mib);
    setVcpus(data.vcpus);
    setNicEdits({});
  }, []);

  const receiveOptions = useCallback((data: VmOptions) => {
    setOpts(data);
    setOptDraft(draftOf(data));
  }, []);

  const reload = useCallback(
    () =>
      Promise.all([api.hardware(vm.uuid), api.options(vm.uuid)])
        .then(([h, o]) => {
          receive(h);
          receiveOptions(o);
        })
        .catch((err: unknown) => notifyError(t("settings.title", { name: vm.name }), err)),
    [vm.uuid, vm.name, receive, receiveOptions, notifyError, t],
  );

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.hardware(vm.uuid), api.host(), api.networks(), api.options(vm.uuid)])
      .then(([h, caps, nets, o]) => {
        if (cancelled) return;
        receive(h);
        receiveOptions(o);
        setHost(caps);
        setNetworks(nets);
      })
      .catch(
        (err: unknown) => !cancelled && notifyError(t("settings.title", { name: vm.name }), err),
      );
    return () => {
      cancelled = true;
    };
  }, [vm.uuid, vm.name, receive, receiveOptions, notifyError, t]);

  const nicOf = (n: HardwareNic): NicEdit =>
    nicEdits[n.mac] ?? { network: n.network, model: n.model, connected: n.connected };

  const optChange = opts && optDraft ? optionsChange(opts, optDraft) : {};
  const renamed = opts !== null && optDraft !== null && optDraft.name.trim() !== opts.name;
  const notesChanged = opts !== null && optDraft !== null && optDraft.notes !== opts.notes;
  const optionsDirty = renamed || notesChanged || Object.keys(optChange).length > 0;
  const invalid =
    optDraft !== null && (!optDraft.boot.some((d) => d.enabled) || !optDraft.name.trim());
  const dirty =
    optionsDirty ||
    (hw !== null &&
      (memory !== hw.memory_mib ||
        vcpus !== hw.vcpus ||
        hw.nics.some((n) => {
          const e = nicEdits[n.mac];
          return (
            e && (e.network !== n.network || e.model !== n.model || e.connected !== n.connected)
          );
        })));

  const apply = async (confirmed = false, close = false): Promise<boolean> => {
    if (!hw) return false;
    if (opts && optDraft && risky(opts, optDraft) && !confirmed) {
      setConfirmRisky({ close });
      return false;
    }
    setBusy(true);
    let restart = false;
    try {
      if (memory !== hw.memory_mib || vcpus !== hw.vcpus) {
        restart = (await api.setCpuMemory(vm.uuid, memory, vcpus)).restart_required || restart;
      }
      for (const nic of hw.nics) {
        const e = nicEdits[nic.mac];
        if (!e) continue;
        const change: NicChange = {};
        if (e.network !== nic.network && e.network) change.network = e.network;
        if (e.model !== nic.model) change.model = e.model as NicChange["model"];
        if (e.connected !== nic.connected) change.connected = e.connected;
        if (Object.keys(change).length) {
          restart = (await api.changeNic(vm.uuid, nic.mac, change)).restart_required || restart;
        }
      }
      if (opts && optDraft) {
        if (Object.keys(optChange).length) {
          const result = await api.setOptions(vm.uuid, { ...optChange, confirmed });
          restart = result.restart_required || restart;
        }
        if (renamed) await api.rename(vm.uuid, optDraft.name.trim());
        if (notesChanged) await api.setNotes(vm.uuid, optDraft.notes);
      }
      if (restart) notify(t("settings.saved"), t("settings.nextBoot"));
      await reload();
      return true;
    } catch (err) {
      notifyError(t("settings.applyFailed", { name: vm.name }), err);
      await reload();
      return false;
    } finally {
      setBusy(false);
    }
  };

  const run = async (action: () => Promise<{ restart_required?: boolean } | unknown>) => {
    setBusy(true);
    try {
      const result = (await action()) as { restart_required?: boolean } | undefined;
      if (result?.restart_required) notify(t("settings.saved"), t("settings.nextBoot"));
    } catch (err) {
      notifyError(t("settings.applyFailed", { name: vm.name }), err);
    } finally {
      setBusy(false);
      await reload();
    }
  };

  const defaultNetwork = networks.find((n) => n.name === "kvmnet8")?.name ?? networks[0]?.name;
  const rows: { sel: Selection; icon: typeof Cpu; label: string; summary: string }[] = hw
    ? [
        {
          sel: { kind: "memory" },
          icon: MemoryStick,
          label: t("summary.memory"),
          summary:
            memory % 1024 === 0
              ? t("units.gib", { value: memory / 1024 })
              : t("units.mib", { value: memory }),
        },
        { sel: { kind: "cpu" }, icon: Cpu, label: t("summary.processors"), summary: String(vcpus) },
        ...hw.disks.map((d) => ({
          sel: { kind: "disk" as const, target: d.target },
          icon: HardDrive,
          label: t("settings.disk", { bus: d.bus.toUpperCase(), target: d.target }),
          summary: fileName(d.path) ?? "",
        })),
        ...hw.cdroms.map((d) => ({
          sel: { kind: "cdrom" as const, target: d.target },
          icon: Disc3,
          label: t("settings.cdrom", { target: d.target }),
          summary: fileName(d.path) ?? t("menu.noMedia"),
        })),
        ...hw.nics.map((n, i) => ({
          sel: { kind: "nic" as const, mac: n.mac },
          icon: NetworkIcon,
          label: t("settings.nic", { index: i + 1 }),
          summary: `${nicOf(n).network ?? "-"}${nicOf(n).connected ? "" : ` (${t("settings.unplugged")})`}`,
        })),
      ]
    : [];
  const same = (a: Selection, b: Selection) => JSON.stringify(a) === JSON.stringify(b);
  const removable = selection.kind === "cdrom" || selection.kind === "nic";

  const nic = selection.kind === "nic" ? hw?.nics.find((n) => n.mac === selection.mac) : undefined;
  const cdrom =
    selection.kind === "cdrom" ? hw?.cdroms.find((d) => d.target === selection.target) : undefined;
  const disk =
    selection.kind === "disk" ? hw?.disks.find((d) => d.target === selection.target) : undefined;

  return (
    <>
      <Dialog
        open
        width={760}
        onOpenChange={(open) => !open && onClose()}
        title={t("settings.title", { name: vm.name })}
        buttons={
          <>
            <button
              type="button"
              className="button button-primary"
              disabled={busy || invalid}
              onClick={() =>
                void (dirty ? apply(false, true) : Promise.resolve(true)).then(
                  (ok) => ok && onClose(),
                )
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
              disabled={!dirty || busy || invalid}
              onClick={() => void apply()}
            >
              {t("common.apply")}
            </button>
          </>
        }
      >
        <div className="settings-tabs" role="tablist">
          {(["hardware", "options"] as const).map((id) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={tab === id}
              className="settings-tab"
              onClick={() => setTab(id)}
            >
              {t(`settings.tab.${id}`)}
            </button>
          ))}
        </div>
        {tab === "options" && opts && optDraft && (
          <OptionsTab options={opts} draft={optDraft} onChange={setOptDraft} />
        )}
        <div className="settings" hidden={tab !== "hardware"}>
          <div className="settings-left">
            <div className="list settings-devices">
              <div className="settings-device settings-device-header" aria-hidden>
                <span>{t("settings.device")}</span>
                <span>{t("settings.summary")}</span>
              </div>
              <ul role="listbox" aria-label={t("settings.device")}>
                {rows.map((row) => (
                  <li
                    key={JSON.stringify(row.sel)}
                    role="option"
                    aria-selected={same(row.sel, selection)}
                    className="list-row settings-device"
                    onClick={() => setSelection(row.sel)}
                  >
                    <span className="settings-device-name">
                      <row.icon aria-hidden />
                      {row.label}
                    </span>
                    <span className="muted">{row.summary}</span>
                  </li>
                ))}
              </ul>
            </div>
            <div className="settings-left-buttons">
              <DropdownMenu.Root>
                <DropdownMenu.Trigger className="button" disabled={busy || !hw}>
                  {t("settings.add")}
                </DropdownMenu.Trigger>
                <DropdownMenu.Portal>
                  <DropdownMenu.Content className="menu" align="start" sideOffset={2}>
                    <DropdownMenu.Item
                      className="menu-item"
                      disabled={!defaultNetwork}
                      onSelect={() =>
                        defaultNetwork &&
                        void run(() => api.addNic(vm.uuid, defaultNetwork, "virtio"))
                      }
                    >
                      <span className="menu-indicator" />
                      <span className="menu-label">{t("settings.addNic")}</span>
                    </DropdownMenu.Item>
                    <DropdownMenu.Item
                      className="menu-item"
                      onSelect={() => void run(() => api.addCdrom(vm.uuid, null))}
                    >
                      <span className="menu-indicator" />
                      <span className="menu-label">{t("settings.addCdrom")}</span>
                    </DropdownMenu.Item>
                  </DropdownMenu.Content>
                </DropdownMenu.Portal>
              </DropdownMenu.Root>
              <button
                type="button"
                className="button"
                disabled={busy || !removable}
                onClick={() => setRemoving(selection)}
              >
                {t("settings.remove")}
              </button>
            </div>
          </div>

          <div className="settings-panel">
            {hw?.active && (
              <p className="note note-warn">
                <TriangleAlert aria-hidden />
                <span>{t("settings.runningNote")}</span>
              </p>
            )}
            {hw && selection.kind === "memory" && (
              <fieldset className="group">
                <legend>{t("summary.memory")}</legend>
                <p>{t("settings.memoryIntro")}</p>
                <label className="settings-inline">
                  {t("settings.memoryLabel")}
                  <input
                    type="number"
                    min={256}
                    step={4}
                    max={host?.memory_mib}
                    value={memory}
                    onChange={(e) => setMemory(Number(e.target.value))}
                  />
                  {t("units.mibShort")}
                </label>
                {host && (
                  <p className="muted">
                    {t("settings.hostMemory", { value: Math.round(host.memory_mib / 1024) })}
                  </p>
                )}
                {memory % 4 !== 0 && <p className="field-error">{t("settings.memoryMultiple")}</p>}
              </fieldset>
            )}
            {hw && selection.kind === "cpu" && (
              <fieldset className="group">
                <legend>{t("summary.processors")}</legend>
                <label className="settings-inline">
                  {t("settings.vcpus")}
                  <input
                    type="number"
                    min={1}
                    max={host?.cpus}
                    value={vcpus}
                    onChange={(e) => setVcpus(Number(e.target.value))}
                  />
                </label>
                {host && <p className="muted">{t("settings.hostCpus", { count: host.cpus })}</p>}
              </fieldset>
            )}
            {disk && <DiskPanel key={disk.target} uuid={vm.uuid} disk={disk} />}
            {cdrom && (
              <fieldset className="group">
                <legend>{t("settings.cdrom", { target: cdrom.target })}</legend>
                <p className="mono">{cdrom.path ?? t("menu.noMedia")}</p>
                <div className="settings-row">
                  <button type="button" className="button" onClick={() => setPicking(cdrom.target)}>
                    {t("menu.changeIso")}
                  </button>
                  <button
                    type="button"
                    className="button"
                    disabled={!cdrom.path}
                    onClick={() => void run(() => api.changeMedia(vm.uuid, cdrom.target, null))}
                  >
                    {t("menu.eject")}
                  </button>
                </div>
              </fieldset>
            )}
            {nic && (
              <fieldset className="group">
                <legend>{t("settings.nicTitle")}</legend>
                <label className="check">
                  <input
                    type="checkbox"
                    checked={nicOf(nic).connected}
                    onChange={(e) =>
                      setNicEdits({
                        ...nicEdits,
                        [nic.mac]: { ...nicOf(nic), connected: e.target.checked },
                      })
                    }
                  />
                  {t("settings.connected")}
                </label>
                <label className="settings-inline">
                  {t("settings.network")}
                  <select
                    value={nicOf(nic).network ?? ""}
                    onChange={(e) =>
                      setNicEdits({
                        ...nicEdits,
                        [nic.mac]: { ...nicOf(nic), network: e.target.value },
                      })
                    }
                  >
                    {nicOf(nic).network === null && <option value="">-</option>}
                    {networks.map((n) => (
                      <option key={n.name} value={n.name}>
                        {n.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="settings-inline">
                  {t("settings.model")}
                  <select
                    value={nicOf(nic).model}
                    onChange={(e) =>
                      setNicEdits({
                        ...nicEdits,
                        [nic.mac]: { ...nicOf(nic), model: e.target.value },
                      })
                    }
                  >
                    {(host?.nic_models ?? ["virtio", "e1000e", "rtl8139", "vmxnet3"]).map((m) => (
                      <option key={m} value={m}>
                        {m}
                      </option>
                    ))}
                  </select>
                </label>
                <p className="muted">
                  {t("settings.mac")} <span className="mono">{nic.mac}</span>
                </p>
                {nic.target && (
                  <p className="muted">
                    {t("settings.hostInterface")} <span className="mono">{nic.target}</span>
                  </p>
                )}
              </fieldset>
            )}
          </div>
        </div>
      </Dialog>
      {picking && (
        <IsoPicker
          title={t("iso.titleFor", { name: vm.name, target: picking })}
          onPick={(path) => {
            const target = picking;
            setPicking(null);
            void run(() => api.changeMedia(vm.uuid, target, path));
          }}
          onClose={() => setPicking(null)}
        />
      )}
      {confirmRisky && (
        <ConfirmDialog
          title={t("options.riskyTitle")}
          message={t("options.riskyConfirm", { name: vm.name })}
          confirmLabel={t("options.riskyApply")}
          danger
          onCancel={() => setConfirmRisky(null)}
          onConfirm={() => {
            const { close } = confirmRisky;
            setConfirmRisky(null);
            void apply(true).then((ok) => ok && close && onClose());
          }}
        />
      )}
      {removing && (
        <ConfirmDialog
          title={t("settings.remove")}
          message={
            removing.kind === "nic"
              ? t("settings.confirmRemoveNic")
              : t("settings.confirmRemoveCdrom")
          }
          confirmLabel={t("settings.remove")}
          danger
          onCancel={() => setRemoving(null)}
          onConfirm={() => {
            const target = removing;
            setRemoving(null);
            setSelection({ kind: "memory" });
            void run(() =>
              target.kind === "nic"
                ? api.removeNic(vm.uuid, target.mac)
                : api.removeCdrom(vm.uuid, (target as { target: string }).target),
            );
          }}
        />
      )}
    </>
  );
}
