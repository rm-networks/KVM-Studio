import RFB from "@novnc/novnc";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { getToken } from "../../api/token";
import { hostClipboard } from "../../platform/hostClipboard";
import { ClipboardBridge } from "./clipboardBridge";
import "./VmConsole.css";

type Status = "connecting" | "connected" | "disconnected";

// X11 keysyms replayed after a paste shortcut.
const XK_V = 0x0076;
const XK_INSERT = 0xff63;
// Lets the guest agent take the clipboard before the paste keystroke arrives.
const PASTE_DELAY_MS = 150;

function consoleUrl(uuid: string): string {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${window.location.host}/api/vms/${encodeURIComponent(uuid)}/console`;
}

function pasteKey(e: KeyboardEvent): [number, string] | null {
  if (e.ctrlKey && !e.altKey && !e.metaKey && e.code === "KeyV") return [XK_V, "KeyV"];
  if (e.shiftKey && !e.ctrlKey && e.code === "Insert") return [XK_INSERT, "Insert"];
  return null;
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export function VmConsole({ uuid }: { uuid: string }) {
  const { t } = useTranslation();
  const screenRef = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState<Status>("connecting");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const screen = screenRef.current;
    if (!screen) return;
    setStatus("connecting");

    const rfb = new RFB(screen, consoleUrl(uuid), {
      shared: true,
      wsProtocols: ["binary", `kvmstudio.${getToken() ?? ""}`],
    });
    rfb.scaleViewport = true;
    rfb.focusOnClick = true;
    rfb.background = "transparent";
    const bridge = new ClipboardBridge(rfb, hostClipboard);

    const onConnect = () => setStatus("connected");
    const onDisconnect = () => setStatus("disconnected");
    const onClipboard = (e: Event) => {
      const text = (e as CustomEvent<{ text: string }>).detail.text;
      void bridge.fromGuest(text);
    };
    const onFocus = () => void bridge.toGuest();
    // Capture phase: runs before noVNC forwards the keystroke to the guest.
    const onKeyDown = (e: KeyboardEvent) => {
      const key = pasteKey(e);
      if (!key) return;
      e.preventDefault();
      e.stopImmediatePropagation();
      void (async () => {
        if (await bridge.toGuest()) await sleep(PASTE_DELAY_MS);
        // The modifier is already down on the guest side; replay the key itself.
        rfb.sendKey(key[0], key[1], true);
        rfb.sendKey(key[0], key[1], false);
      })();
    };

    rfb.addEventListener("connect", onConnect);
    rfb.addEventListener("disconnect", onDisconnect);
    rfb.addEventListener("clipboard", onClipboard);
    screen.addEventListener("focusin", onFocus);
    screen.addEventListener("keydown", onKeyDown, { capture: true });

    return () => {
      screen.removeEventListener("focusin", onFocus);
      screen.removeEventListener("keydown", onKeyDown, { capture: true });
      rfb.removeEventListener("connect", onConnect);
      rfb.removeEventListener("disconnect", onDisconnect);
      rfb.removeEventListener("clipboard", onClipboard);
      rfb.disconnect();
    };
  }, [uuid, attempt]);

  return (
    <div className="console">
      <div className="console-screen" ref={screenRef} />
      {status !== "connected" && (
        <div className="console-overlay">
          {status === "connecting" ? (
            <span>{t("console.connecting")}</span>
          ) : (
            <>
              <span>{t("console.disconnected")}</span>
              <button type="button" className="button" onClick={() => setAttempt((n) => n + 1)}>
                {t("console.reconnect")}
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
