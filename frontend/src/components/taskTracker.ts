import { createContext, useContext } from "react";

import type { TaskInfo } from "../api/client";

export interface TrackedTask {
  info: TaskInfo;
  /** Shown in the status bar while it runs: "Snapshot of FW-OPN". */
  label: string;
  /** Notified when it ends well. */
  doneTitle: string;
  cancelling: boolean;
}

export interface TaskTracker {
  tasks: TrackedTask[];
  track: (
    info: TaskInfo,
    label: string,
    doneTitle: string,
    onEnd?: (info: TaskInfo) => void,
  ) => void;
  cancel: (id: string) => void;
}

export const TaskTrackerContext = createContext<TaskTracker>({
  tasks: [],
  track: () => {},
  cancel: () => {},
});

export function useTasks(): TaskTracker {
  return useContext(TaskTrackerContext);
}
