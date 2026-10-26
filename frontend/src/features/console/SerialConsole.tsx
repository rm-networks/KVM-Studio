import { FitAddon } from "@xterm/addon-fit";
import { Terminal } from "@xterm/xterm";
import "@xterm/xterm/css/xterm.css";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { getToken } from "../../api/token";
import "./SerialConsole.css";

type Status = "connecting" | "connected" | "closed";

function serialUrl(uuid: string): string {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${window.location.host}/api/vms/${encodeURIComponent(uuid)}/serial`;
}

/** Serial console of a VM (F-63): xterm.js over the libvirt console stream. */
export function SerialConsole({ uuid }: { uuid: string }) {
  const { t } = useTranslation();
  const boxRef = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState<Status>("connecting");
  const [reason, setReason] = useState("");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const box = boxRef.current;
    if (!box) return;
    const term = new Terminal({
      convertEol: false,
      cursorBlink: true,
      fontFamily: "monospace",
      fontSize: 14,
      scrollback: 5000,
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(box);
    fit.fit();
    const resize = new ResizeObserver(() => fit.fit());
    resize.observe(box);

    const socket = new WebSocket(serialUrl(uuid), ["binary", `kvmstudio.${getToken() ?? ""}`]);
    socket.binaryType = "arraybuffer";
    const encoder = new TextEncoder();
    socket.onopen = () => {
      setStatus("connected");
      term.focus();
    };
    socket.onmessage = (e: MessageEvent<ArrayBuffer>) => term.write(new Uint8Array(e.data));
    socket.onclose = (e) => {
      setStatus("closed");
      setReason(e.code >= 4000 ? e.reason : "");
    };
    const typed = term.onData((data) => {
      if (socket.readyState === WebSocket.OPEN) socket.send(encoder.encode(data));
    });
    return () => {
      typed.dispose();
      resize.disconnect();
      socket.close();
      term.dispose();
    };
  }, [uuid, attempt]);

  return (
    <div className="serial-console">
      <div className="serial-screen" ref={boxRef} />
      {status !== "connected" && (
        <div className="serial-overlay">
          {status === "connecting" ? (
            <span>{t("serial.connecting")}</span>
          ) : (
            <>
              <span>
                {reason
                  ? t(`errors.${reason}`, { defaultValue: t("serial.closed") })
                  : t("serial.closed")}
              </span>
              <button
                type="button"
                className="button"
                onClick={() => {
                  setStatus("connecting");
                  setAttempt((n) => n + 1);
                }}
              >
                {t("console.reconnect")}
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
