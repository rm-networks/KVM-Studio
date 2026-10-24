import type { Network, ProfileInfo } from "../../api/client";

export interface NicDraft {
  network: string;
  model: ProfileInfo["nic_model"];
}

/**
 * First card on NAT (kvmnet8 when present), the others on host-only networks,
 * like a firewall lab: WAN on NAT, LAN and DMZ on isolated segments.
 */
export function defaultNics(profile: ProfileInfo, networks: Network[]): NicDraft[] {
  if (networks.length === 0) return [];
  const nat =
    networks.find((n) => n.name === "kvmnet8") ??
    networks.find((n) => n.kind === "nat") ??
    networks[0];
  const hostOnly = networks.filter((n) => n.kind === "host_only" && n.name !== nat?.name);
  const result: NicDraft[] = [];
  for (let i = 0; i < profile.nics; i++) {
    const network = i === 0 ? nat : (hostOnly[i - 1] ?? hostOnly.at(-1) ?? nat);
    if (network) result.push({ network: network.name, model: profile.nic_model });
  }
  return result;
}

/** A name not used yet: "Windows 11", then "Windows 11-2"... */
export function uniqueName(base: string, taken: ReadonlySet<string>): string {
  const clean = base.replace(/[/\\]/g, "-").trim().slice(0, 60) || "VM";
  if (!taken.has(clean)) return clean;
  for (let i = 2; ; i++) {
    const candidate = `${clean}-${i}`;
    if (!taken.has(candidate)) return candidate;
  }
}

/** "Win11_24H2_French_x64.iso" -> "Win11_24H2_French_x64" */
export function nameFromIso(path: string): string {
  const file = path.slice(path.lastIndexOf("/") + 1);
  return file.replace(/\.(iso|img)$/i, "");
}
