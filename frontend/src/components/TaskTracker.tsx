import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, ApiError, type TaskInfo } from "../api/client";
import { useNotifier } from "./notifier";
import { type TaskTracker, type TrackedTask, TaskTrackerContext } from "./taskTracker";

const POLL_MS = 1000;

/** Background tasks the status bar follows after their dialog is closed. */
export function TaskTrackerProvider({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const { notify, notifyError } = useNotifier();
  const [tasks, setTasks] = useState<TrackedTask[]>([]);
  const endings = useRef(new Map<string, (info: TaskInfo) => void>());

  const finish = useCallback(
    (task: TrackedTask, info: TaskInfo) => {
      setTasks((list) => list.filter((x) => x.info.id !== info.id));
      if (info.state === "done") notify(task.doneTitle);
      else if (info.state === "cancelled") notify(t("tasks.cancelled", { label: task.label }));
      else
        notifyError(
          task.label,
          new ApiError(0, info.error_code ?? "task.failed", info.error_detail ?? ""),
        );
      endings.current.get(info.id)?.(info);
      endings.current.delete(info.id);
    },
    [notify, notifyError, t],
  );

  const track = useCallback<TaskTracker["track"]>(
    (info, label, doneTitle, onEnd) => {
      const task = { info, label, doneTitle, cancelling: false };
      if (onEnd) endings.current.set(info.id, onEnd);
      if (info.state !== "running") finish(task, info);
      else setTasks((list) => [...list, task]);
    },
    [finish],
  );

  const cancel = useCallback((id: string) => {
    setTasks((list) => list.map((x) => (x.info.id === id ? { ...x, cancelling: true } : x)));
    api.cancelTask(id).catch(() => undefined);
  }, []);

  useEffect(() => {
    if (tasks.length === 0) return;
    const timer = setTimeout(() => {
      for (const task of tasks) {
        api
          .task(task.info.id)
          .then((info) => {
            if (info.state === "running")
              setTasks((list) => list.map((x) => (x.info.id === info.id ? { ...x, info } : x)));
            else finish(task, info);
          })
          .catch((err: unknown) => {
            setTasks((list) => list.filter((x) => x.info.id !== task.info.id));
            notifyError(task.label, err);
          });
      }
    }, POLL_MS);
    return () => clearTimeout(timer);
  }, [tasks, finish, notifyError]);

  return (
    <TaskTrackerContext.Provider value={{ tasks, track, cancel }}>
      {children}
    </TaskTrackerContext.Provider>
  );
}
