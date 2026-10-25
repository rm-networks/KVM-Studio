import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { NotificationProvider } from "../../components/Notifications";
import { makeVm } from "../../test/fixtures";
import { VmActionsProvider } from "../vm/VmActions";
import { FullscreenBar } from "./FullscreenBar";

const BAR_HIDE_MS = 2000;

afterEach(() => {
  vi.useRealTimers();
});

describe("FullscreenBar", () => {
  it("comes out at the top edge and hides 2 s later", () => {
    vi.useFakeTimers();
    const sendCtrlAltDel = vi.fn();
    const onExit = vi.fn();
    render(
      <NotificationProvider>
        <VmActionsProvider>
          <FullscreenBar
            vm={makeVm({ name: "OPNsense", state: "running" })}
            vmConsole={{ sendCtrlAltDel, sendKeys: vi.fn(), grab: vi.fn(), grabbed: true }}
            onExit={onExit}
          />
        </VmActionsProvider>
      </NotificationProvider>,
    );
    const bar = screen.getByRole("toolbar", { name: "OPNsense" });
    expect(bar.dataset.visible).toBe("false");

    fireEvent.mouseMove(window, { clientY: 300 });
    expect(bar.dataset.visible).toBe("false");
    fireEvent.mouseMove(window, { clientY: 0 });
    expect(bar.dataset.visible).toBe("true");
    act(() => vi.advanceTimersByTime(BAR_HIDE_MS + 10));
    expect(bar.dataset.visible).toBe("false");

    // Stays while the pointer is on it.
    fireEvent.mouseMove(window, { clientY: 1 });
    fireEvent.mouseEnter(bar);
    act(() => vi.advanceTimersByTime(BAR_HIDE_MS * 3));
    expect(bar.dataset.visible).toBe("true");

    fireEvent.click(screen.getByRole("button", { name: /Ctrl\+Alt\+Suppr/ }));
    expect(sendCtrlAltDel).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: /Quitter le plein écran/ }));
    expect(onExit).toHaveBeenCalledTimes(1);
  });
});
