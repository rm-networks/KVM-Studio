import RFB from "@novnc/novnc";
import { type ReactNode, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, type DisplayInfo } from "../../api/client";
import { getToken } from "../../api/token";
import { LoadingCubes } from "../../components/LoadingCubes";
import { useNotifier } from "../../components/notifier";
import { hostClipboard } from "../../platform/hostClipboard";
import { ConfirmDialog } from "../vm/ConfirmDialog";
import { useBootSplash } from "./bootSplash";
import { ClipboardBridge } from "./clipboardBridge";
import { registerConsole, unregisterConsole, updateConsole } from "./consoleRegistry";
import { pressCombo } from "./keys";
import "./VmConsole.css";

type Status = "connecting" | "connected" | "disconnected" | "timeout";

// A console that has not answered by then will not: say so instead of waiting.
const CONNECT_TIMEOUT_MS = 15_000;

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
  const { notifyError } = useNotifier();
  const [display, setDisplay] = useState<DisplayInfo | null>(null);
  const [check, setCheck] = useState(0);
  const [confirming, setConfirming] = useState(false);
  const [connected, setConnected] = useState(false);
  const splash = useBootSplash(uuid, connected);

  useEffect(() => {
    let cancelled = false;
    api
      .display(uuid)
      .then((info) => !cancelled && setDisplay(info))
      .catch((err: unknown) => !cancelled && notifyError(t("console.title"), err));
    return () => {
      cancelled = true;
    };
  }, [uuid, check, notifyError, t]);

  if (display === null) {
    return (
      <div className="console">
        {splash ? (
          <BootSplash />
        ) : (
          <div className="console-overlay console-loading">
            <LoadingCubes message={t("console.connecting")} />
          </div>
        )}
      </div>
    );
  }
  if (display.live.includes("vnc")) {
    return (
      <VncScreen uuid={uuid} splash={splash} onConnected={setConnected}>
        {!display.clipboard && (
          <ClipboardNotice
            uuid={uuid}
            pending={display.clipboard_config}
            onChanged={() => setCheck((n) => n + 1)}
          />
        )}
      </VncScreen>
    );
  }

  // A SPICE display (virt-manager): turning copy and paste on also gives the
  // console the display it uses, so it is the only thing to offer.
  const spice = display.live.includes("spice") || display.config.includes("spice");
  if (spice) {
    return (
      <div className="console">
        <ClipboardNotice
          uuid={uuid}
          centered
          pending={display.config.includes("vnc") && display.clipboard_config}
          onChanged={() => setCheck((n) => n + 1)}
        />
      </div>
    );
  }

  const vncConfigured = display.config.includes("vnc");
  return (
    <div className="console">
      <div className="console-overlay console-notice">
        {vncConfigured ? (
          <span>{t("console.restartForVnc")}</span>
        ) : (
          <>
            <span>{t("console.noDisplay")}</span>
            <button type="button" className="button" onClick={() => setConfirming(true)}>
              {t("console.addVnc")}
            </button>
          </>
        )}
      </div>
      {confirming && (
        <ConfirmDialog
          title={t("console.addVnc")}
          message={t("console.addVncConfirm")}
          confirmLabel={t("console.addVnc")}
          onCancel={() => setConfirming(false)}
          onConfirm={() => {
            setConfirming(false);
            api
              .addVnc(uuid)
              .then(() => setCheck((n) => n + 1))
              .catch((err: unknown) => notifyError(t("console.addVnc"), err));
          }}
        />
      )}
    </div>
  );
}

/** Copy and paste is off: the agent port belongs to SPICE, or there is no agent channel. */
function ClipboardNotice({
  uuid,
  pending,
  centered = false,
  onChanged,
}: {
  uuid: string;
  pending: boolean;
  /** Alone on the console (no screen yet) rather than over the screen. */
  centered?: boolean;
  onChanged: () => void;
}) {
  const { t } = useTranslation();
  const { notifyError } = useNotifier();
  const [confirming, setConfirming] = useState(false);
  return (
    <div className={centered ? "console-overlay console-notice" : "console-banner"}>
      <span>{pending ? t("console.restartForClipboard") : t("console.clipboardOff")}</span>
      {!pending && (
        <button type="button" className="button" onClick={() => setConfirming(true)}>
          {t("console.enableClipboard")}
        </button>
      )}
      {confirming && (
        <ConfirmDialog
          title={t("console.enableClipboard")}
          message={t("console.enableClipboardConfirm")}
          confirmLabel={t("console.enableClipboard")}
          onCancel={() => setConfirming(false)}
          onConfirm={() => {
            setConfirming(false);
            api
              .enableClipboard(uuid)
              .then(onChanged)
              .catch((err: unknown) => notifyError(t("console.enableClipboard"), err));
          }}
        />
      )}
    </div>
  );
}

/** Over the firmware logo at start; clicks and keys go through to the guest. */
function BootSplash() {
  const { t } = useTranslation();
  return (
    <div className="console-overlay console-loading console-splash">
      <LoadingCubes message={t("console.starting")} />
    </div>
  );
}

function VncScreen({
  uuid,
  splash = false,
  onConnected,
  children,
}: {
  uuid: string;
  splash?: boolean;
  onConnected?: (connected: boolean) => void;
  children?: ReactNode;
}) {
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

    const timer = setTimeout(() => {
      setStatus((s) => (s === "connecting" ? "timeout" : s));
    }, CONNECT_TIMEOUT_MS);
    const onConnect = () => {
      clearTimeout(timer);
      setStatus("connected");
      registerConsole(uuid, {
        sendCtrlAltDel: () => rfb.sendCtrlAltDel(),
        sendKeys: (keys) => pressCombo((s, c, d) => rfb.sendKey(s, c, d), keys),
        grab: () => rfb.focus(),
        grabbed: false,
      });
    };
    const onDisconnect = () => {
      clearTimeout(timer);
      unregisterConsole(uuid);
      setStatus((s) => (s === "timeout" ? s : "disconnected"));
    };
    const onClipboard = (e: Event) => {
      const text = (e as CustomEvent<{ text: string }>).detail.text;
      void bridge.fromGuest(text);
    };
    const onFocus = () => {
      updateConsole(uuid, { grabbed: true });
      void bridge.toGuest();
    };
    const onBlur = (e: FocusEvent) => {
      if (!screen.contains(e.relatedTarget as Node | null)) updateConsole(uuid, { grabbed: false });
    };
    // Ctrl+Alt pressed and released alone gives the keyboard back to the host.
    let releasePending = false;
    const onKeyUp = (e: KeyboardEvent) => {
      if (releasePending && (e.key === "Control" || e.key === "Alt")) {
        releasePending = false;
        (document.activeElement as HTMLElement | null)?.blur();
      }
    };
    // Capture phase: runs before noVNC forwards the keystroke to the guest.
    const onKeyDown = (e: KeyboardEvent) => {
      releasePending = (e.key === "Alt" && e.ctrlKey) || (e.key === "Control" && e.altKey);
      if (e.ctrlKey && e.altKey && e.key === "Enter") {
        // Full screen key for the host (handled at the window level), not the guest.
        e.stopImmediatePropagation();
        return;
      }
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
    screen.addEventListener("focusout", onBlur);
    screen.addEventListener("keydown", onKeyDown, { capture: true });
    screen.addEventListener("keyup", onKeyUp, { capture: true });

    return () => {
      clearTimeout(timer);
      unregisterConsole(uuid);
      screen.removeEventListener("focusin", onFocus);
      screen.removeEventListener("focusout", onBlur);
      screen.removeEventListener("keydown", onKeyDown, { capture: true });
      screen.removeEventListener("keyup", onKeyUp, { capture: true });
      rfb.removeEventListener("connect", onConnect);
      rfb.removeEventListener("disconnect", onDisconnect);
      rfb.removeEventListener("clipboard", onClipboard);
      rfb.disconnect();
    };
  }, [uuid, attempt]);

  useEffect(() => {
    onConnected?.(status === "connected");
  }, [status, onConnected]);

  return (
    <div className="console">
      <div className="console-screen" ref={screenRef} />
      {children}
      {splash && <BootSplash />}
      {!splash && status !== "connected" && (
        <div
          className={
            status === "connecting" ? "console-overlay console-loading" : "console-overlay"
          }
        >
          {status === "connecting" ? (
            <LoadingCubes message={t("console.connecting")} />
          ) : (
            <>
              <span>{status === "timeout" ? t("console.timeout") : t("console.disconnected")}</span>
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
