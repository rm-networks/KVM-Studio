import type { PowerAction, VmState } from "../../api/client";

export const POWER_ACTIONS: PowerAction[] = ["start", "shutdown", "reboot", "poweroff", "reset"];

/** Which power actions make sense in a given state. */
export function powerAllowed(state: VmState, action: PowerAction): boolean {
  const active = state !== "shutoff" && state !== "crashed";
  switch (action) {
    case "start":
      return !active;
    case "shutdown":
    case "reboot":
      return state === "running";
    case "reset":
      return state === "running" || state === "paused";
    case "poweroff":
      return active;
  }
}
