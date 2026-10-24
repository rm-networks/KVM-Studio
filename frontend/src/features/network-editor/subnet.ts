// IPv4 helpers for the network editor. The backend checks everything again.

export function ipToInt(ip: string): number | null {
  const parts = ip.trim().split(".");
  if (parts.length !== 4) return null;
  let value = 0;
  for (const part of parts) {
    if (!/^\d{1,3}$/.test(part)) return null;
    const n = Number(part);
    if (n > 255) return null;
    value = value * 256 + n;
  }
  return value;
}

export function intToIp(value: number): string {
  return [24, 16, 8, 0].map((shift) => Math.floor(value / 2 ** shift) % 256).join(".");
}

export function prefixFromMask(mask: string): number | null {
  const value = ipToInt(mask);
  if (value === null) return null;
  const bits = value.toString(2).padStart(32, "0");
  if (!/^1*0*$/.test(bits)) return null;
  return bits.indexOf("0") === -1 ? 32 : bits.indexOf("0");
}

export function maskFromPrefix(prefix: number): string {
  return intToIp(prefix === 0 ? 0 : (2 ** 32 - 2 ** (32 - prefix)) >>> 0);
}

/** "192.168.150.0/24" -> address and mask fields; null for "" or garbage. */
export function splitCidr(cidr: string | null): { ip: string; mask: string } {
  if (!cidr || !cidr.includes("/")) return { ip: "", mask: "255.255.255.0" };
  const [ip = "", prefix = "24"] = cidr.split("/");
  return { ip, mask: maskFromPrefix(Number(prefix)) };
}

/** Address and mask fields -> "network/prefix", or null if invalid. */
export function joinCidr(ip: string, mask: string): string | null {
  const address = ipToInt(ip);
  const prefix = prefixFromMask(mask);
  if (address === null || prefix === null || prefix < 8 || prefix > 30) return null;
  const size = 2 ** (32 - prefix);
  const network = address - (address % size);
  return `${intToIp(network)}/${prefix}`;
}

/** Upper half of the subnet's hosts, like the backend default (.128 to .254 on a /24). */
export function defaultDhcp(cidr: string): { start: string; end: string } | null {
  const [ip = "", prefixText = ""] = cidr.split("/");
  const network = ipToInt(ip);
  const prefix = Number(prefixText);
  if (network === null || !(prefix >= 8 && prefix <= 30)) return null;
  const size = 2 ** (32 - prefix);
  const firstHost = network + 1;
  const lastHost = network + size - 2;
  const hostCount = lastHost - firstHost + 1;
  return { start: intToIp(firstHost + Math.floor(hostCount / 2)), end: intToIp(lastHost) };
}
