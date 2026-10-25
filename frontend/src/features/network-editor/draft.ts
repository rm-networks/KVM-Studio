import type { Network, NetworkSettings } from "../../api/client";
import { intToIp, ipToInt, joinCidr, splitCidr } from "./subnet";

/** What the editor panel edits before "Apply" sends it. */
export interface Draft {
  kind: "host_only" | "nat";
  ip: string;
  mask: string;
  hostAdapter: boolean;
  /** The host's address on the network; "" for the first one. */
  hostIp: string;
  dhcpEnabled: boolean;
  dhcpStart: string;
  dhcpEnd: string;
  gateway: "host" | "custom" | "none";
  gatewayIp: string;
}

export function draftFrom(network: Network): Draft | null {
  if (network.kind === "other") return null;
  const { ip, mask } = splitCidr(network.subnet);
  return {
    kind: network.kind,
    ip,
    mask,
    hostAdapter: network.host_ip !== null,
    hostIp: network.host_ip ?? "",
    dhcpEnabled: network.dhcp !== null,
    dhcpStart: network.dhcp?.start ?? "",
    dhcpEnd: network.dhcp?.end ?? "",
    gateway: network.gateway ?? (network.kind === "nat" ? "host" : "none"),
    gatewayIp: network.gateway_ip ?? "",
  };
}

export function sameDraft(a: Draft, b: Draft): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

/** First usable address of a subnet ("192.168.150.0/24" -> "192.168.150.1"). */
export function firstHost(cidr: string): string {
  const network = ipToInt(cidr.split("/")[0] ?? "");
  return network === null ? "" : intToIp(network + 1);
}

/** The DHCP range moved off the host address when it falls inside, like the backend. */
export function fittedRange(draft: Draft, cidr: string): { start: string; end: string } {
  const start = ipToInt(draft.dhcpStart);
  const end = ipToInt(draft.dhcpEnd);
  const host = ipToInt(draft.hostIp.trim() || firstHost(cidr));
  const same = { start: draft.dhcpStart.trim(), end: draft.dhcpEnd.trim() };
  if (start === null || end === null || host === null || host < start || host > end) return same;
  if (host === start && host === end) return same;
  return end - host >= host - start
    ? { start: intToIp(host + 1), end: same.end }
    : { start: same.start, end: intToIp(host - 1) };
}

export type DraftResult =
  { settings: NetworkSettings } | { error: "subnet" | "dhcp" | "hostIp" | "gateway" };

function inSubnet(ip: string, cidr: string): boolean {
  const [base = "", prefixText = ""] = cidr.split("/");
  const value = ipToInt(ip);
  const network = ipToInt(base);
  if (value === null || network === null) return false;
  const size = 2 ** (32 - Number(prefixText));
  return value > network && value < network + size - 1;
}

/** Turn the panel fields into the API body; NAT always has the host address. */
export function settingsFrom(draft: Draft): DraftResult {
  const hostAdapter = draft.kind === "nat" || draft.hostAdapter;
  if (!hostAdapter) return { settings: { kind: draft.kind, host_adapter: false } };
  const subnet = joinCidr(draft.ip, draft.mask);
  if (subnet === null) return { error: "subnet" };
  const hostIp = draft.hostIp.trim();
  if (hostIp && !inSubnet(hostIp, subnet)) return { error: "hostIp" };
  const base = { kind: draft.kind, subnet, host_adapter: true, host_ip: hostIp || null };
  if (!draft.dhcpEnabled) return { settings: base };
  if (!draft.dhcpStart.trim() || !draft.dhcpEnd.trim()) return { error: "dhcp" };
  const gateway = draft.kind === "host_only" ? draft.gateway : "host";
  if (gateway === "custom" && !inSubnet(draft.gatewayIp.trim(), subnet)) {
    return { error: "gateway" };
  }
  return {
    settings: {
      ...base,
      dhcp: fittedRange(draft, subnet),
      gateway,
      gateway_ip: gateway === "custom" ? draft.gatewayIp.trim() : null,
    },
  };
}
