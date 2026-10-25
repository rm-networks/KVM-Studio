import { createContext, useContext } from "react";

import type { VmSummary } from "../../api/client";

export interface LibraryActions {
  /** False until a VM location is configured: folders cannot exist yet. */
  available: boolean;
  newFolder: (parent: string) => void;
  renameFolder: (path: string) => void;
  deleteFolder: (path: string) => void;
  /** With a folder: move right away (drag and drop). Without: ask where. */
  moveVm: (vm: VmSummary, folder?: string) => void;
  importVm: (vm: VmSummary) => void;
  /**
   * Drag and drop of a folder: under another parent, its VMs move with it
   * (after a confirmation); in the same parent, only the display order changes.
   */
  moveFolder: (path: string, parent: string, before: string | null) => void;
}

export const LibraryActionsContext = createContext<LibraryActions | null>(null);

export function useLibraryActions(): LibraryActions {
  const actions = useContext(LibraryActionsContext);
  if (!actions) throw new Error("useLibraryActions outside LibraryActionsProvider");
  return actions;
}
