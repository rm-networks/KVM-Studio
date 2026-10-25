import { useSyncExternalStore } from "react";

// People on each VM console (shared console, F-104), from the live events.
const counts = new Map<string, number>();
const listeners = new Set<() => void>();

export function setViewers(uuid: string, count: number): void {
  if (count > 0) counts.set(uuid, count);
  else counts.delete(uuid);
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useViewers(uuid: string): number {
  return useSyncExternalStore(subscribe, () => counts.get(uuid) ?? 0);
}
