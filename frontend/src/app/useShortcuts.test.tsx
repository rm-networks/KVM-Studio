import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { type ShortcutActions, useShortcuts } from "./useShortcuts";

function Harness({ actions }: { actions: ShortcutActions }) {
  useShortcuts(actions);
  return (
    <>
      <input aria-label="field" />
      <div className="console-screen">
        <canvas tabIndex={0} aria-label="guest" />
      </div>
    </>
  );
}

function actions(): ShortcutActions {
  return {
    newVm: vi.fn(),
    closeTab: vi.fn(),
    nextTab: vi.fn(),
    previousTab: vi.fn(),
    preferences: vi.fn(),
    settings: vi.fn(),
    grab: vi.fn(),
    consoleFullscreen: vi.fn(),
    appFullscreen: vi.fn(),
  };
}

describe("useShortcuts", () => {
  it("maps Workstation shortcuts", () => {
    const a = actions();
    render(<Harness actions={a} />);
    fireEvent.keyDown(window, { key: "n", ctrlKey: true });
    fireEvent.keyDown(window, { key: "w", ctrlKey: true });
    fireEvent.keyDown(window, { key: "Tab", ctrlKey: true });
    fireEvent.keyDown(window, { key: "Tab", ctrlKey: true, shiftKey: true });
    fireEvent.keyDown(window, { key: "p", ctrlKey: true });
    fireEvent.keyDown(window, { key: "g", ctrlKey: true });
    fireEvent.keyDown(window, { key: "d", ctrlKey: true });
    fireEvent.keyDown(window, { key: "Enter", ctrlKey: true, altKey: true });
    fireEvent.keyDown(window, { key: "F11" });
    for (const fn of Object.values(a)) expect(fn).toHaveBeenCalledTimes(1);
  });

  it("leaves the guest and text fields alone, except full screen", () => {
    const a = actions();
    const { getByLabelText } = render(<Harness actions={a} />);
    fireEvent.keyDown(getByLabelText("guest"), { key: "w", ctrlKey: true });
    fireEvent.keyDown(getByLabelText("field"), { key: "n", ctrlKey: true });
    expect(a.closeTab).not.toHaveBeenCalled();
    expect(a.newVm).not.toHaveBeenCalled();
    fireEvent.keyDown(getByLabelText("guest"), { key: "Enter", ctrlKey: true, altKey: true });
    expect(a.consoleFullscreen).toHaveBeenCalledTimes(1);
    // F11 belongs to the guest while the console holds the keyboard.
    fireEvent.keyDown(getByLabelText("guest"), { key: "F11" });
    expect(a.appFullscreen).not.toHaveBeenCalled();
  });
});
