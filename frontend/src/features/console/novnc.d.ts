// The parts of noVNC's RFB class used by KVM Studio (noVNC ships no types).
declare module "@novnc/novnc" {
  export interface RfbOptions {
    shared?: boolean;
    wsProtocols?: string[];
  }

  export default class RFB extends EventTarget {
    constructor(target: HTMLElement, url: string, options?: RfbOptions);
    scaleViewport: boolean;
    resizeSession: boolean;
    focusOnClick: boolean;
    viewOnly: boolean;
    background: string;
    disconnect(): void;
    sendCtrlAltDel(): void;
    sendKey(keysym: number, code: string | null, down?: boolean): void;
    clipboardPasteFrom(text: string): void;
    focus(options?: FocusOptions): void;
  }
}
