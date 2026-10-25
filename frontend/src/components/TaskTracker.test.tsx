import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { TaskInfo } from "../api/client";
import { StatusBar } from "../app/StatusBar";
import { NotificationProvider } from "./Notifications";
import { TaskTrackerProvider } from "./TaskTracker";
import { useTasks } from "./taskTracker";

const running: TaskInfo = {
  id: "t1",
  kind: "snapshot",
  state: "running",
  progress: 0,
  step: "",
  result: { vm: "u1" },
  error_code: null,
  error_detail: null,
};

function Start({ onEnd }: { onEnd: () => void }) {
  const { track } = useTasks();
  return (
    <button type="button" onClick={() => track(running, "Instantané de FW", "Pris", onEnd)}>
      start
    </button>
  );
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("TaskTracker", () => {
  it("follows a task in the status bar, cancels it and tells when it ends", async () => {
    vi.useFakeTimers();
    let state: TaskInfo = running;
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((path: string, init?: RequestInit) => {
        calls.push(`${init?.method ?? "GET"} ${path}`);
        return Promise.resolve(new Response(JSON.stringify(state)));
      }),
    );
    const onEnd = vi.fn();
    render(
      <NotificationProvider>
        <TaskTrackerProvider>
          <Start onEnd={onEnd} />
          <StatusBar info={null} vms={[]} libvirtLost={false} vmConsole={null} />
        </TaskTrackerProvider>
      </NotificationProvider>,
    );
    fireEvent.click(screen.getByText("start"));
    // No percentage from libvirt: the label alone and a moving bar.
    expect(screen.getByText("Instantané de FW")).toBeTruthy();
    expect(screen.getByRole("progressbar").getAttribute("aria-valuenow")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Annuler : Instantané de FW" }));
    expect(calls).toContain("POST /api/tasks/t1/cancel");
    expect(screen.getByText("Instantané de FW : annulation…")).toBeTruthy();

    state = { ...running, state: "cancelled" };
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1100);
    });
    expect(screen.queryByRole("progressbar")).toBeNull();
    expect(screen.getByText("Instantané de FW : annulé")).toBeTruthy();
    expect(onEnd).toHaveBeenCalledTimes(1);
  });
});
