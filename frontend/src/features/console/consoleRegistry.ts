import { useSyncExternalStore } from "react";

import type { Key } from "./keys";

/** What the menus and the toolbar can do with a connected console. */
export interface ConsoleHandle {
  sendKeys: (keys: Key[]) => void;
  grab: () => void;
  grabbed: boolean;
}

const consoles = new Map<string, ConsoleHandle>();
const listeners = new Set<() => void>();
let version = 0;

function changed() {
  version += 1;
  for (const listener of listeners) listener();
}

export function registerConsole(uuid: string, handle: ConsoleHandle): void {
  consoles.set(uuid, handle);
  changed();
}

export function updateConsole(uuid: string, patch: Partial<ConsoleHandle>): void {
  const current = consoles.get(uuid);
  if (!current) return;
  consoles.set(uuid, { ...current, ...patch });
  changed();
}

export function unregisterConsole(uuid: string): void {
  if (consoles.delete(uuid)) changed();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** The connected console of a VM, or null; re-renders when it changes. */
export function useConsole(uuid: string | undefined): ConsoleHandle | null {
  useSyncExternalStore(subscribe, () => version);
  return uuid ? (consoles.get(uuid) ?? null) : null;
}

// Autofit Guest (View menu): the guest display follows the console's size.
let autofit = true;
const autofitListeners = new Set<() => void>();

export function getAutofit(): boolean {
  return autofit;
}

export function setAutofit(value: boolean): void {
  autofit = value;
  for (const listener of autofitListeners) listener();
}

export function subscribeAutofit(listener: () => void): () => void {
  autofitListeners.add(listener);
  return () => autofitListeners.delete(listener);
}

export function useAutofit(): boolean {
  return useSyncExternalStore(subscribeAutofit, getAutofit);
}
