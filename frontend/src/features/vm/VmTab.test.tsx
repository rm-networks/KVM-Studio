import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { makeVm } from "../../test/fixtures";
import { VmTab } from "./VmTab";

vi.mock("./vmActionsContext", () => ({ useVmActions: () => ({}) }));
vi.mock("../console/VmConsole", () => ({ VmConsole: () => <div>vnc screen</div> }));
vi.mock("../console/SerialConsole", () => ({ SerialConsole: () => <div>serial terminal</div> }));

function display(live: string[], serial: boolean) {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve(
        new Response(
          JSON.stringify({
            live,
            config: live,
            clipboard: false,
            clipboard_config: false,
            active: true,
            serial,
          }),
        ),
      ),
    ),
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("VmTab", () => {
  it("offers the serial console next to the screen", async () => {
    display(["vnc"], true);
    render(<VmTab vm={makeVm({ name: "FW", state: "running" })} onSettings={vi.fn()} />);
    fireEvent.click(await screen.findByRole("tab", { name: "Console série" }));
    expect(screen.getByText("serial terminal")).toBeTruthy();
    fireEvent.click(screen.getByRole("tab", { name: "Écran" }));
    expect(screen.getByText("vnc screen")).toBeTruthy();
  });

  it("opens the serial console of an appliance without a display", async () => {
    display([], true);
    render(<VmTab vm={makeVm({ name: "OPN", state: "running" })} onSettings={vi.fn()} />);
    expect(await screen.findByText("serial terminal")).toBeTruthy();
  });

  it("shows the screen alone without a serial console", async () => {
    display(["vnc"], false);
    render(<VmTab vm={makeVm({ name: "W11", state: "running" })} onSettings={vi.fn()} />);
    expect(await screen.findByText("vnc screen")).toBeTruthy();
    expect(screen.queryByRole("tab")).toBeNull();
  });
});
