import { createContext, useContext } from "react";

export interface Notifier {
  notifyError: (title: string, err: unknown) => void;
  notify: (title: string, text?: string) => void;
}

export const NotifierContext = createContext<Notifier>({ notifyError: () => {}, notify: () => {} });

export function useNotifier(): Notifier {
  return useContext(NotifierContext);
}
