import { describe, expect, it } from "vitest";

import { defaultDhcp, joinCidr, maskFromPrefix, prefixFromMask, splitCidr } from "./subnet";

describe("subnet helpers", () => {
  it("converts masks and prefixes", () => {
    expect(prefixFromMask("255.255.255.0")).toBe(24);
    expect(prefixFromMask("255.255.240.0")).toBe(20);
    expect(prefixFromMask("255.0.255.0")).toBeNull();
    expect(maskFromPrefix(24)).toBe("255.255.255.0");
    expect(maskFromPrefix(16)).toBe("255.255.0.0");
  });

  it("splits and joins CIDR notation", () => {
    expect(splitCidr("10.1.0.0/16")).toEqual({ ip: "10.1.0.0", mask: "255.255.0.0" });
    expect(splitCidr(null)).toEqual({ ip: "", mask: "255.255.255.0" });
    expect(joinCidr("192.168.150.7", "255.255.255.0")).toBe("192.168.150.0/24");
    expect(joinCidr("192.168.150.0", "255.255.255.255")).toBeNull();
    expect(joinCidr("192.168.300.0", "255.255.255.0")).toBeNull();
  });

  it("proposes the upper half for DHCP", () => {
    expect(defaultDhcp("192.168.150.0/24")).toEqual({
      start: "192.168.150.128",
      end: "192.168.150.254",
    });
    expect(defaultDhcp("10.0.0.0/30")).toEqual({ start: "10.0.0.2", end: "10.0.0.2" });
  });
});
