import { fireEvent, render, screen } from "@testing-library/react";
import { beforeAll, describe, expect, it } from "vitest";

import { Dialog } from "./Dialog";

describe("Dialog", () => {
  beforeAll(() => {
    // Not in jsdom.
    HTMLElement.prototype.setPointerCapture = () => undefined;
    HTMLElement.prototype.getBoundingClientRect = () =>
      ({ left: 300, right: 700, top: 200, bottom: 500, width: 400, height: 300 }) as DOMRect;
  });

  it("moves by its title bar and opens centred again", () => {
    const view = (open: boolean) => (
      <Dialog open={open} onOpenChange={() => undefined} title="Préférences" buttons={null}>
        body
      </Dialog>
    );
    const { rerender } = render(view(true));
    const bar = screen.getByText("Préférences").parentElement as HTMLElement;
    fireEvent.pointerDown(bar, { button: 0, clientX: 100, clientY: 100, pointerId: 1 });
    fireEvent.pointerMove(bar, { clientX: 140, clientY: 130, pointerId: 1 });
    fireEvent.pointerUp(bar, { pointerId: 1 });
    expect(screen.getByRole("dialog").style.transform).toBe(
      "translate(calc(-50% + 40px), calc(-50% + 30px))",
    );
    fireEvent.pointerMove(bar, { clientX: 300, clientY: 300, pointerId: 1 });
    expect(screen.getByRole("dialog").style.transform).toContain("40px");
    rerender(view(false));
    rerender(view(true));
    expect(screen.getByRole("dialog").style.transform).toBe(
      "translate(calc(-50% + 0px), calc(-50% + 0px))",
    );
  });
});
