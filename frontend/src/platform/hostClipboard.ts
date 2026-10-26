// Host clipboard access. The desktop window exposes it through pywebview (the
// embedded engine blocks navigator.clipboard); browsers use the standard API,
// available on 127.0.0.1 and HTTPS.

interface DesktopApi {
  read_clipboard(): Promise<string>;
  write_clipboard(text: string): Promise<void>;
  choose_folder(start: string | null): Promise<string | null>;
  choose_disk(start: string | null): Promise<string | null>;
  save_file(name: string, text: string): Promise<boolean>;
  close_window(): Promise<void>;
  guard_close(on: boolean): Promise<void>;
  close_answered(): Promise<void>;
  open_link(url: string): Promise<void>;
}

declare global {
  interface Window {
    pywebview?: { api?: Partial<DesktopApi> };
  }
}

export interface HostClipboard {
  read(): Promise<string | null>;
  write(text: string): Promise<void>;
}

export const hostClipboard: HostClipboard = {
  async read() {
    try {
      const api = window.pywebview?.api;
      if (api?.read_clipboard) return await api.read_clipboard();
      if (navigator.clipboard?.readText) return await navigator.clipboard.readText();
    } catch {
      // Permission refused or no clipboard: nothing to paste.
    }
    return null;
  },

  async write(text) {
    try {
      const api = window.pywebview?.api;
      if (api?.write_clipboard) await api.write_clipboard(text);
      else await navigator.clipboard?.writeText(text);
    } catch {
      // Ignored: the browser may refuse while the page is not focused.
    }
  },
};
