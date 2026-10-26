import { createContext, useContext } from "react";

/** A button on a notice, which closes it. */
export interface NoticeAction {
  label: string;
  run: () => void;
}

export interface Notifier {
  notifyError: (title: string, err: unknown) => void;
  /** Returns the notice's id, for dismiss(). A notice with an action stays until closed. */
  notify: (title: string, text?: string, action?: NoticeAction) => number;
  dismiss: (id: number) => void;
}

export const NotifierContext = createContext<Notifier>({
  notifyError: () => {},
  notify: () => 0,
  dismiss: () => {},
});

export function useNotifier(): Notifier {
  return useContext(NotifierContext);
}
