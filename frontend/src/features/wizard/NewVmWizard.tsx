import { Disc3, Plus, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  api,
  type HostCapabilities,
  type LibraryInfo,
  type Network,
  type ProfileInfo,
  type VmSummary,
} from "../../api/client";
import { Dialog } from "../../components/Dialog";
import { useNotifier } from "../../components/notifier";
import { IsoPicker } from "../iso-picker/IsoPicker";
import { isValidName } from "../library/names";
import { defaultNics, type NicDraft, uniqueName } from "./defaults";
import "./NewVmWizard.css";

type Step = "source" | "os" | "name" | "disk" | "summary";
const STEPS: Step[] = ["source", "os", "name", "disk", "summary"];
type Source = "iso" | "later" | "existing";

interface Props {
  library: LibraryInfo | null;
  vms: VmSummary[];
  initialFolder?: string;
  onCreated: (uuid: string, name: string) => void;
  onClose: () => void;
}

export function NewVmWizard({ library, vms, initialFolder = "", onCreated, onClose }: Props) {
  const { t } = useTranslation();
  const { notifyError } = useNotifier();
  const [step, setStep] = useState<Step>("source");
  const [profiles, setProfiles] = useState<ProfileInfo[]>([]);
  const [host, setHost] = useState<HostCapabilities | null>(null);
  const [networks, setNetworks] = useState<Network[]>([]);
  const [pickingIso, setPickingIso] = useState(false);
  const [busy, setBusy] = useState(false);
  const [customize, setCustomize] = useState(false);

  const [source, setSource] = useState<Source>("iso");
  const [iso, setIso] = useState<string | null>(null);
  const [existingDisk, setExistingDisk] = useState("");
  const [profileId, setProfileId] = useState("linux");
  const [name, setName] = useState("");
  const [nameTouched, setNameTouched] = useState(false);
  const [folder, setFolder] = useState(initialFolder);
  const [diskGib, setDiskGib] = useState(25);
  const [diskBus, setDiskBus] = useState<ProfileInfo["disk_bus"]>("virtio");
  const [diskFormat, setDiskFormat] = useState<"qcow2" | "raw">("qcow2");
  const [preallocate, setPreallocate] = useState(false);
  const [memory, setMemory] = useState(2048);
  const [vcpus, setVcpus] = useState(2);
  const [nics, setNics] = useState<NicDraft[]>([]);
  const [uefi, setUefi] = useState(true);
  const [secureBoot, setSecureBoot] = useState(false);
  const [tpm, setTpm] = useState(false);
  const [start, setStart] = useState(true);

  const taken = useMemo(() => new Set(vms.map((v) => v.name)), [vms]);
  const profile = profiles.find((p) => p.id === profileId);

  // Picking a profile resets the hardware to what suits it.
  const applyProfile = (
    id: string,
    loaded?: { profiles: ProfileInfo[]; host: HostCapabilities; networks: Network[] },
  ) => {
    const all = loaded?.profiles ?? profiles;
    const caps = loaded?.host ?? host;
    const nets = loaded?.networks ?? networks;
    const p = all.find((x) => x.id === id);
    setProfileId(id);
    if (!p) return;
    setMemory(p.memory_mib);
    setVcpus(p.vcpus);
    setDiskGib(p.disk_gib);
    setDiskBus(caps && !caps.disk_buses.includes(p.disk_bus) ? "sata" : p.disk_bus);
    setUefi(p.uefi && (caps?.uefi ?? true));
    setSecureBoot(p.secure_boot && (caps?.secure_boot ?? true));
    setTpm(p.tpm && (caps?.tpm ?? true));
    setNics(defaultNics(p, nets));
    if (!nameTouched) setName(uniqueName(t(`wizard.profile.${id}`), taken));
  };

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.profiles(), api.host(), api.networks()])
      .then(([p, h, n]) => {
        if (cancelled) return;
        setProfiles(p);
        setHost(h);
        setNetworks(n);
        applyProfile("linux", { profiles: p, host: h, networks: n });
      })
      .catch((err: unknown) => !cancelled && notifyError(t("wizard.title"), err));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- load once
  }, []);

  const chooseIso = (path: string) => {
    setIso(path);
    setPickingIso(false);
    api
      .guessProfile(path)
      .then((g) => applyProfile(g.profile))
      .catch(() => undefined);
  };

  const noLibrary = !library?.root;
  const sourceReady =
    source === "later" ||
    (source === "iso" && iso !== null) ||
    (source === "existing" && existingDisk.trim() !== "");
  const nameValid = isValidName(name) && !taken.has(name);
  const stepReady: Record<Step, boolean> = {
    source: sourceReady,
    os: profile !== undefined,
    name: nameValid && !noLibrary,
    disk: source === "existing" || diskGib >= 1,
    summary: true,
  };
  const index = STEPS.indexOf(step);
  const visible = STEPS.filter((s) => !(s === "disk" && source === "existing"));
  const goto = (delta: number) => {
    const at = visible.indexOf(step);
    const next = visible[at + delta];
    if (next) setStep(next);
  };

  const finish = async () => {
    setBusy(true);
    try {
      const created = await api.createVm({
        name,
        folder,
        profile: profileId,
        iso: source === "iso" ? iso : null,
        existing_disk: source === "existing" ? existingDisk.trim() : null,
        disk_gib: source === "existing" ? 0 : diskGib,
        disk_bus: diskBus,
        disk_format: diskFormat,
        preallocate,
        memory_mib: memory,
        vcpus,
        nics,
        uefi,
        secure_boot: uefi && secureBoot,
        tpm,
        start,
      });
      onCreated(created.uuid, name);
      onClose();
    } catch (err) {
      notifyError(t("wizard.failed", { name }), err);
      setBusy(false);
    }
  };

  const libraryPath = library?.root ? `${library.root}${folder ? `/${folder}` : ""}/${name}` : "";

  return (
    <>
      <Dialog
        open
        width={640}
        onOpenChange={(open) => !open && !busy && onClose()}
        title={t("wizard.title")}
        buttons={
          <>
            <button
              type="button"
              className="button"
              disabled={index === 0 || busy}
              onClick={() => goto(-1)}
            >
              {t("wizard.back")}
            </button>
            {step !== "summary" ? (
              <button
                type="button"
                className="button button-primary"
                disabled={!stepReady[step]}
                onClick={() => goto(1)}
              >
                {t("wizard.next")}
              </button>
            ) : (
              <button
                type="button"
                className="button button-primary"
                disabled={busy || !nameValid || noLibrary}
                onClick={() => void finish()}
              >
                {busy ? t("wizard.creating") : t("wizard.finish")}
              </button>
            )}
            <button type="button" className="button" disabled={busy} onClick={onClose}>
              {t("common.cancel")}
            </button>
          </>
        }
      >
        <ol className="wizard-steps">
          {visible.map((s) => (
            <li key={s} className={s === step ? "current" : undefined}>
              {t(`wizard.step.${s}`)}
            </li>
          ))}
        </ol>

        {step === "source" && (
          <div className="wizard-page">
            <p>{t("wizard.sourceIntro")}</p>
            <label className="wizard-choice">
              <input type="radio" checked={source === "iso"} onChange={() => setSource("iso")} />
              {t("wizard.sourceIso")}
            </label>
            {source === "iso" && (
              <div className="wizard-indent wizard-iso">
                <Disc3 size={14} aria-hidden />
                <span className="wizard-mono">{iso ?? t("wizard.noIso")}</span>
                <button type="button" className="button" onClick={() => setPickingIso(true)}>
                  {t("wizard.chooseIso")}
                </button>
              </div>
            )}
            <label className="wizard-choice">
              <input
                type="radio"
                checked={source === "later"}
                onChange={() => setSource("later")}
              />
              {t("wizard.sourceLater")}
            </label>
            <label className="wizard-choice">
              <input
                type="radio"
                checked={source === "existing"}
                onChange={() => setSource("existing")}
              />
              {t("wizard.sourceExisting")}
            </label>
            {source === "existing" && (
              <div className="wizard-indent">
                <input
                  type="text"
                  className="wizard-input wizard-mono"
                  value={existingDisk}
                  placeholder="/…/KVM-Studio/VM/appliance.qcow2"
                  onChange={(e) => setExistingDisk(e.target.value)}
                />
                <p className="wizard-muted">{t("wizard.existingHint")}</p>
              </div>
            )}
          </div>
        )}

        {step === "os" && (
          <div className="wizard-page">
            <p>{t("wizard.osIntro")}</p>
            <ul className="wizard-profiles" role="listbox">
              {profiles.map((p) => (
                <li
                  key={p.id}
                  role="option"
                  aria-selected={p.id === profileId}
                  className={p.id === profileId ? "selected" : undefined}
                  onClick={() => applyProfile(p.id)}
                >
                  <strong>{t(`wizard.profile.${p.id}`)}</strong>
                  <span>{t(`wizard.profileHint.${p.id}`)}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {step === "name" && (
          <div className="wizard-page">
            {noLibrary && <p className="field-error">{t("wizard.noLibrary")}</p>}
            <label className="field">
              <span>{t("wizard.vmName")}</span>
              <input
                type="text"
                className="wizard-input"
                value={name}
                maxLength={64}
                autoFocus
                onChange={(e) => {
                  setNameTouched(true);
                  setName(e.target.value);
                }}
              />
            </label>
            {name !== "" && !isValidName(name) && (
              <p className="field-error">{t("rename.invalid")}</p>
            )}
            {taken.has(name) && <p className="field-error">{t("errors.vm.exists")}</p>}
            <label className="field">
              <span>{t("wizard.folder")}</span>
              <select
                className="wizard-input"
                value={folder}
                onChange={(e) => setFolder(e.target.value)}
              >
                <option value="">{t("library.myComputer")}</option>
                {(library?.folders ?? []).map((f) => (
                  <option key={f} value={f}>
                    {f}
                  </option>
                ))}
              </select>
            </label>
            {libraryPath && <p className="wizard-muted wizard-mono">{libraryPath}</p>}
          </div>
        )}

        {step === "disk" && (
          <div className="wizard-page">
            <label className="field wizard-inline">
              <span>{t("wizard.diskSize")}</span>
              <input
                type="number"
                min={1}
                max={16384}
                className="wizard-input wizard-narrow"
                value={diskGib}
                onChange={(e) => setDiskGib(Number(e.target.value))}
              />
              <span>{t("units.gb")}</span>
            </label>
            <label className="field wizard-inline">
              <span>{t("wizard.diskBus")}</span>
              <select
                className="wizard-input"
                value={diskBus}
                onChange={(e) => setDiskBus(e.target.value as ProfileInfo["disk_bus"])}
              >
                {(host?.disk_buses ?? ["virtio", "sata"]).map((b) => (
                  <option key={b} value={b}>
                    {t(`wizard.bus.${b}`)}
                  </option>
                ))}
              </select>
            </label>
            <label className="field wizard-inline">
              <span>{t("wizard.diskFormat")}</span>
              <select
                className="wizard-input"
                value={diskFormat}
                onChange={(e) => setDiskFormat(e.target.value as "qcow2" | "raw")}
              >
                <option value="qcow2">{t("wizard.qcow2")}</option>
                <option value="raw">{t("wizard.raw")}</option>
              </select>
            </label>
            <label className="wizard-choice">
              <input
                type="checkbox"
                checked={preallocate}
                onChange={(e) => setPreallocate(e.target.checked)}
              />
              {t("wizard.preallocate")}
            </label>
            {profile?.family === "windows" && diskBus === "sata" && (
              <p className="wizard-muted">{t("wizard.windowsSata")}</p>
            )}
          </div>
        )}

        {step === "summary" && (
          <div className="wizard-page">
            <table className="wizard-summary">
              <tbody>
                <tr>
                  <td>{t("wizard.vmName")}</td>
                  <td>{name}</td>
                </tr>
                <tr>
                  <td>{t("wizard.step.os")}</td>
                  <td>{t(`wizard.profile.${profileId}`)}</td>
                </tr>
                <tr>
                  <td>{t("wizard.location")}</td>
                  <td className="wizard-mono">{libraryPath}</td>
                </tr>
                <tr>
                  <td>{t("summary.memory")}</td>
                  <td>
                    {memory >= 1024
                      ? t("units.gib", { value: memory / 1024 })
                      : t("units.mib", { value: memory })}
                  </td>
                </tr>
                <tr>
                  <td>{t("summary.processors")}</td>
                  <td>{vcpus}</td>
                </tr>
                <tr>
                  <td>{t("wizard.disk")}</td>
                  <td>
                    {source === "existing"
                      ? existingDisk
                      : `${diskGib} ${t("units.gb")}, ${t(`wizard.bus.${diskBus}`)}, ${diskFormat}${preallocate ? `, ${t("wizard.preallocated")}` : ""}`}
                  </td>
                </tr>
                <tr>
                  <td>CD/DVD</td>
                  <td className="wizard-mono">
                    {source === "iso" && iso ? iso : t("menu.noMedia")}
                  </td>
                </tr>
                <tr>
                  <td>{t("wizard.network")}</td>
                  <td>{nics.map((n) => `${n.network} (${n.model})`).join(", ") || "-"}</td>
                </tr>
                <tr>
                  <td>{t("wizard.firmware")}</td>
                  <td>
                    {uefi ? "UEFI" : "BIOS"}
                    {uefi && secureBoot ? ", Secure Boot" : ""}
                    {tpm ? ", TPM 2.0" : ""}
                  </td>
                </tr>
              </tbody>
            </table>
            <button
              type="button"
              className="button wizard-customize"
              onClick={() => setCustomize((c) => !c)}
            >
              {t("wizard.customize")}
            </button>
            {customize && (
              <div className="wizard-hardware">
                <label className="field wizard-inline">
                  <span>{t("summary.memory")}</span>
                  <input
                    type="number"
                    min={256}
                    step={256}
                    max={host?.memory_mib}
                    className="wizard-input wizard-narrow"
                    value={memory}
                    onChange={(e) => setMemory(Number(e.target.value))}
                  />
                  <span>{t("units.mibShort")}</span>
                </label>
                <label className="field wizard-inline">
                  <span>{t("summary.processors")}</span>
                  <input
                    type="number"
                    min={1}
                    max={host?.cpus}
                    className="wizard-input wizard-narrow"
                    value={vcpus}
                    onChange={(e) => setVcpus(Number(e.target.value))}
                  />
                </label>
                <div className="wizard-nics">
                  <span>{t("wizard.network")}</span>
                  {nics.map((nic, i) => (
                    <div key={i} className="wizard-nic">
                      <select
                        className="wizard-input"
                        value={nic.network}
                        onChange={(e) =>
                          setNics(
                            nics.map((n, j) => (j === i ? { ...n, network: e.target.value } : n)),
                          )
                        }
                      >
                        {networks.map((n) => (
                          <option key={n.name} value={n.name}>
                            {n.name}
                          </option>
                        ))}
                      </select>
                      <select
                        className="wizard-input"
                        value={nic.model}
                        onChange={(e) =>
                          setNics(
                            nics.map((n, j) =>
                              j === i ? { ...n, model: e.target.value as NicDraft["model"] } : n,
                            ),
                          )
                        }
                      >
                        {(host?.nic_models ?? ["virtio"]).map((m) => (
                          <option key={m} value={m}>
                            {m}
                          </option>
                        ))}
                      </select>
                      <button
                        type="button"
                        className="library-button"
                        title={t("wizard.removeNic")}
                        aria-label={t("wizard.removeNic")}
                        onClick={() => setNics(nics.filter((_n, j) => j !== i))}
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  ))}
                  <button
                    type="button"
                    className="button"
                    disabled={networks.length === 0 || nics.length >= 10}
                    onClick={() =>
                      networks[0] &&
                      setNics([
                        ...nics,
                        { network: networks[0].name, model: profile?.nic_model ?? "virtio" },
                      ])
                    }
                  >
                    <Plus size={13} /> {t("wizard.addNic")}
                  </button>
                </div>
                <label className="wizard-choice">
                  <input
                    type="checkbox"
                    checked={uefi}
                    disabled={!host?.uefi}
                    onChange={(e) => setUefi(e.target.checked)}
                  />
                  UEFI
                </label>
                <label className="wizard-choice wizard-indent">
                  <input
                    type="checkbox"
                    checked={uefi && secureBoot}
                    disabled={!uefi || !host?.secure_boot}
                    onChange={(e) => setSecureBoot(e.target.checked)}
                  />
                  Secure Boot
                </label>
                <label className="wizard-choice">
                  <input
                    type="checkbox"
                    checked={tpm}
                    disabled={!host?.tpm}
                    onChange={(e) => setTpm(e.target.checked)}
                  />
                  TPM 2.0
                </label>
              </div>
            )}
            <label className="wizard-choice">
              <input type="checkbox" checked={start} onChange={(e) => setStart(e.target.checked)} />
              {t("wizard.startAfter")}
            </label>
          </div>
        )}
      </Dialog>
      {pickingIso && <IsoPicker onPick={chooseIso} onClose={() => setPickingIso(false)} />}
    </>
  );
}
