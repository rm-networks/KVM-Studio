import type { Network, NetworkSettings } from "../../api/client";
import { joinCidr, splitCidr } from "./subnet";

/** What the editor panel edits before "Apply" sends it. */
export interface Draft {
  kind: "host_only" | "nat";
  ip: string;
  mask: string;
  hostAdapter: boolean;
  dhcpEnabled: boolean;
  dhcpStart: string;
  dhcpEnd: string;
}

export function draftFrom(network: Network): Draft | null {
  if (network.kind === "other") return null;
  const { ip, mask } = splitCidr(network.subnet);
  return {
    kind: network.kind,
    ip,
    mask,
    hostAdapter: network.host_ip !== null,
    dhcpEnabled: network.dhcp !== null,
    dhcpStart: network.dhcp?.start ?? "",
    dhcpEnd: network.dhcp?.end ?? "",
  };
}

export function sameDraft(a: Draft, b: Draft): boolean {
  return (Object.keys(a) as (keyof Draft)[]).every((key) => a[key] === b[key]);
}

export type DraftResult = { settings: NetworkSettings } | { error: "subnet" | "dhcp" };

/** Turn the panel fields into the API body; NAT always has the host address. */
export function settingsFrom(draft: Draft): DraftResult {
  const hostAdapter = draft.kind === "nat" || draft.hostAdapter;
  if (!hostAdapter) return { settings: { kind: draft.kind, host_adapter: false } };
  const subnet = joinCidr(draft.ip, draft.mask);
  if (subnet === null) return { error: "subnet" };
  if (!draft.dhcpEnabled) {
    return { settings: { kind: draft.kind, subnet, host_adapter: true } };
  }
  if (!draft.dhcpStart.trim() || !draft.dhcpEnd.trim()) return { error: "dhcp" };
  return {
    settings: {
      kind: draft.kind,
      subnet,
      host_adapter: true,
      dhcp: { start: draft.dhcpStart.trim(), end: draft.dhcpEnd.trim() },
    },
  };
}
