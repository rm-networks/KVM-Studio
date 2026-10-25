import { describe, expect, it } from "vitest";

import type { Network, ProfileInfo } from "../../api/client";
import { defaultNics, nameFromIso, uniqueName } from "./defaults";

function net(name: string, kind: Network["kind"]): Network {
  return {
    name,
    kind,
    forward_mode: kind === "nat" ? "nat" : null,
    bridge: name,
    managed: true,
    active: true,
    autostart: true,
    persistent: true,
    subnet: null,
    host_ip: null,
    dhcp: null,
    gateway: "host",
    gateway_ip: null,
  };
}

const firewall = { nics: 3, nic_model: "virtio" } as ProfileInfo;
const linux = { nics: 1, nic_model: "virtio" } as ProfileInfo;

describe("defaultNics", () => {
  it("puts a firewall's WAN on NAT and its LANs on host-only networks", () => {
    const networks = [
      net("default", "nat"),
      net("kvmnet1", "host_only"),
      net("kvmnet8", "nat"),
      net("LAN-2", "host_only"),
    ];
    expect(defaultNics(firewall, networks).map((n) => n.network)).toEqual([
      "kvmnet8",
      "kvmnet1",
      "LAN-2",
    ]);
    expect(defaultNics(linux, networks)).toEqual([{ network: "kvmnet8", model: "virtio" }]);
  });

  it("copes with few networks", () => {
    expect(defaultNics(firewall, [net("default", "nat")]).map((n) => n.network)).toEqual([
      "default",
      "default",
      "default",
    ]);
    expect(defaultNics(linux, [])).toEqual([]);
  });
});

describe("names", () => {
  it("avoids names already taken", () => {
    expect(uniqueName("Windows 11", new Set())).toBe("Windows 11");
    expect(uniqueName("Windows 11", new Set(["Windows 11", "Windows 11-2"]))).toBe("Windows 11-3");
    expect(uniqueName("a/b", new Set())).toBe("a-b");
  });

  it("derives a name from an ISO file", () => {
    expect(nameFromIso("/srv/iso/Win11_24H2.iso")).toBe("Win11_24H2");
    expect(nameFromIso("opnsense.IMG")).toBe("opnsense");
  });
});
