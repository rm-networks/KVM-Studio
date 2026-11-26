import { useSyncExternalStore } from "react";

// People on each VM console (shared console, F-104), from the live events.
const counts = new Map<string, number>();
const listeners = new Set<() => void>();

export function setViewers(uuid: string, count: number): void {
  if (count > 0) counts.set(uuid, count);
  else counts.delete(uuid);
  for (const listener of listeners) listener();
}

export function getViewers(uuid: string): number {
  return counts.get(uuid) ?? 0;
}

// From two people on, the guest keeps its resolution (the server holds back
// resize requests too): each one scales the picture to the window.
export function isShared(uuid: string): boolean {
  return getViewers(uuid) >= 2;
}

export function subscribeViewers(listener: () => void): () => void {
  return subscribe(listener);
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useViewers(uuid: string): number {
  return useSyncExternalStore(subscribe, () => getViewers(uuid));
}
