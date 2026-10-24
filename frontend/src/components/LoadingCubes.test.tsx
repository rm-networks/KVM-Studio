import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import "../i18n";
import { LoadingCubes } from "./LoadingCubes";

describe("LoadingCubes", () => {
  it("shows the name under the cubes, still when animations are off", () => {
    const { container } = render(<LoadingCubes message="Connexion à la console…" />);
    expect(screen.getByText("KVM Studio")).toBeTruthy();
    expect(screen.getByText("Connexion à la console…")).toBeTruthy();
    const source = container.querySelector("picture source");
    expect(source?.getAttribute("media")).toBe("(prefers-reduced-motion: reduce)");
    // Small pictures are inlined by Vite: compare the two images instead of names.
    const still = source?.getAttribute("srcset");
    const animated = container.querySelector("img")?.getAttribute("src");
    expect(still).toBeTruthy();
    expect(animated).toBeTruthy();
    expect(still).not.toBe(animated);
  });
});
