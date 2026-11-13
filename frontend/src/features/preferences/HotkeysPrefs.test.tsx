import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { DEFAULT_HOTKEYS, type Hotkey } from "../console/hotkeys";
import { HotkeysPrefs } from "./HotkeysPrefs";

function Harness({ onList }: { onList: (list: Hotkey[] | null) => void }) {
  const [list, setList] = useState<Hotkey[] | null>(null);
  const change = (next: Hotkey[] | null) => {
    setList(next);
    onList(next);
  };
  return (
    <HotkeysPrefs
      hotkeys={list ?? DEFAULT_HOTKEYS}
      isDefault={list === null}
      onChange={change}
      onReset={() => change(null)}
    />
  );
}

const rows = () => screen.getAllByRole("option").map((el) => el.textContent);

describe("HotkeysPrefs", () => {
  it("adds, renames, changes, removes and restores the combinations", () => {
    const saves: (Hotkey[] | null)[] = [];
    render(<Harness onList={(l) => saves.push(l)} />);
    const saved = () => saves.at(-1);
    expect(rows().slice(0, 3)).toEqual(["Ctrl+Alt+Suppr", "Ctrl+Maj+Échap", "Win"]);
    expect(screen.getByRole("button", { name: "Rétablir les valeurs par défaut" })).toHaveProperty(
      "disabled",
      true,
    );

    // A new one: Ctrl+Shift+Win+S, named.
    fireEvent.click(screen.getByRole("button", { name: "Ajouter" }));
    for (const m of ["Ctrl", "Maj", "Win"]) fireEvent.click(screen.getByLabelText(m));
    fireEvent.change(screen.getByLabelText("Touche"), { target: { value: "S" } });
    fireEvent.change(screen.getByLabelText("Nom"), { target: { value: "Capture" } });
    fireEvent.click(screen.getAllByRole("button", { name: "Ajouter" })[1] as HTMLElement);
    expect(saved()?.at(-1)).toEqual({ name: "Capture", keys: ["Ctrl", "Shift", "Win", "S"] });
    expect(rows().at(-1)).toBe("CaptureCtrl+Maj+Win+S");

    // Rename the first one and make it Win+E.
    fireEvent.click(screen.getByText("Ctrl+Alt+Suppr"));
    fireEvent.click(screen.getByRole("button", { name: "Modifier" }));
    fireEvent.click(screen.getByLabelText("Ctrl"));
    fireEvent.click(screen.getByLabelText("Alt"));
    fireEvent.click(screen.getByLabelText("Win"));
    fireEvent.change(screen.getByLabelText("Touche"), { target: { value: "E" } });
    fireEvent.change(screen.getByLabelText("Nom"), { target: { value: "Explorer" } });
    fireEvent.click(screen.getByRole("button", { name: "Appliquer" }));
    expect(saved()?.[0]).toEqual({ name: "Explorer", keys: ["Win", "E"] });

    fireEvent.click(screen.getByRole("button", { name: "Supprimer" }));
    expect(saved()).toHaveLength(DEFAULT_HOTKEYS.length);
    expect(rows()[0]).toBe("Ctrl+Maj+Échap");

    fireEvent.click(screen.getByRole("button", { name: "Rétablir les valeurs par défaut" }));
    expect(saved()).toBeNull();
    expect(rows()[0]).toBe("Ctrl+Alt+Suppr");
  });
});
