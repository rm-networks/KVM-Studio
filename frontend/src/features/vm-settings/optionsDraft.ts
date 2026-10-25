import type { BootDevice, VmOptions, VmOptionsChange } from "../../api/client";

export const PROFILE_IDS = [
  "windows11",
  "windows10",
  "windows-server",
  "linux",
  "firewall",
  "nested",
  "other",
] as const;

export interface OptionsDraft {
  name: string;
  profile: string | null;
  autostart: boolean;
  on_reboot: string;
  on_crash: string;
  firmware: "uefi" | "bios";
  secure_boot: boolean;
  tpm: boolean;
  boot_menu: boolean;
  boot: BootDevice[];
  clipboard: boolean;
}

export function draftOf(o: VmOptions): OptionsDraft {
  return {
    name: o.name,
    profile: o.profile,
    autostart: o.autostart,
    on_reboot: o.on_reboot,
    on_crash: o.on_crash,
    firmware: o.firmware,
    secure_boot: o.secure_boot,
    tpm: o.tpm,
    boot_menu: o.boot_menu,
    boot: o.boot,
    clipboard: o.clipboard,
  };
}

export const sameBoot = (a: BootDevice[], b: BootDevice[]) =>
  a.length === b.length &&
  a.every((d, i) => d.kind === b[i]?.kind && d.id === b[i]?.id && d.enabled === b[i]?.enabled);

/** What the user changed, as the API wants it (the name goes through a rename). */
export type OptionsEdit = Omit<VmOptionsChange, "confirmed">;

export function optionsChange(o: VmOptions, d: OptionsDraft): OptionsEdit {
  const change: OptionsEdit = {};
  if (d.profile !== o.profile && d.profile) change.profile = d.profile;
  if (d.autostart !== o.autostart) change.autostart = d.autostart;
  if (d.on_reboot !== o.on_reboot) change.on_reboot = d.on_reboot as OptionsEdit["on_reboot"];
  if (d.on_crash !== o.on_crash) change.on_crash = d.on_crash as OptionsEdit["on_crash"];
  if (d.firmware !== o.firmware) change.firmware = d.firmware;
  const secure = d.firmware === "uefi" && d.secure_boot;
  if (secure !== o.secure_boot) change.secure_boot = secure;
  if (d.tpm !== o.tpm) change.tpm = d.tpm;
  if (d.boot_menu !== o.boot_menu) change.boot_menu = d.boot_menu;
  if (!sameBoot(d.boot, o.boot)) {
    change.boot = d.boot.map(({ kind, id, enabled }) => ({ kind, id, enabled }));
  }
  if (d.clipboard !== o.clipboard) change.clipboard = d.clipboard;
  return change;
}

/** Changes that may stop an installed system from starting. */
export function risky(o: VmOptions, d: OptionsDraft): boolean {
  return o.installed && (d.firmware !== o.firmware || (o.tpm && !d.tpm));
}
