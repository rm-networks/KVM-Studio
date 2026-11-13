import type { VmSummary } from "./client";
import { getToken } from "./token";

export type ServerEvent =
  | { type: "vm.changed"; vm: VmSummary }
  | { type: "vm.removed"; uuid: string }
  | { type: "library.changed" }
  | { type: "snapshots.changed"; uuid: string }
  | { type: "console.viewers"; uuid: string; count: number }
  | { type: "connection"; state: "lost" | "restored" }
  /** The running VMs hold more host memory than the limit of Preferences (bytes). */
  | { type: "memory.over"; used: number; limit: number };

interface Handlers {
  onEvent: (event: ServerEvent) => void;
  /** The socket came back after a drop: events may have been missed. */
  onReconnect: () => void;
}

const MAX_RETRY_DELAY_MS = 10_000;

export function subscribeEvents({ onEvent, onReconnect }: Handlers): () => void {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  const url = `${scheme}://${window.location.host}/ws/events`;
  let socket: WebSocket | null = null;
  let stopped = false;
  let wasOpen = false;
  let attempt = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;

  const connect = () => {
    socket = new WebSocket(url, ["kvmstudio.events", `kvmstudio.${getToken() ?? ""}`]);
    socket.onopen = () => {
      if (wasOpen) onReconnect();
      wasOpen = true;
      attempt = 0;
    };
    socket.onmessage = (message: MessageEvent<string>) => {
      try {
        onEvent(JSON.parse(message.data) as ServerEvent);
      } catch {
        // Ignore anything that is not one of our messages.
      }
    };
    socket.onclose = () => {
      if (stopped) return;
      const delay = Math.min(MAX_RETRY_DELAY_MS, 1000 * 2 ** attempt++);
      timer = setTimeout(connect, delay);
    };
  };

  connect();
  return () => {
    stopped = true;
    clearTimeout(timer);
    socket?.close();
  };
}
