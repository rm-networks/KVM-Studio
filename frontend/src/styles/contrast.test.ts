import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

// Read from disk: the test runner hands style sheets to modules empty.
const tokens = readFileSync(join(process.cwd(), "src", "styles", "tokens.css"), "utf-8");

// Text colour, background: every pair the screens put together.
const PAIRS: [string, string][] = [
  ["--text", "--bg"],
  ["--text", "--surface"],
  ["--text", "--surface-alt"],
  ["--text", "--hover"],
  ["--text", "--info-bg"],
  ["--text-muted", "--bg"],
  ["--text-muted", "--surface"],
  ["--text-muted", "--surface-alt"],
  ["--text-muted", "--surface-sunken"],
  ["--text-muted", "--hover"],
  ["--text-disabled", "--button-disabled"],
  ["--text-disabled", "--surface"],
  ["--accent-text", "--accent"],
  ["--accent-text", "--accent-hover"],
  ["--selection-text", "--selection"],
  ["--accent-fg", "--surface"],
  ["--accent-fg", "--bg"],
  ["--warn-text", "--warn-bg"],
  ["--danger-text", "--danger-bg"],
];

function block(css: string, selector: string): Record<string, string> {
  const start = css.indexOf(selector);
  const body = css.slice(css.indexOf("{", start) + 1, css.indexOf("}", start));
  return Object.fromEntries(
    [...body.matchAll(/(--[\w-]+):\s*(#[0-9a-f]{6})/gi)].map((m) => [m[1], m[2]]),
  );
}

function luminance(hex: string): number {
  const channel = (i: number) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(1) + 0.7152 * channel(3) + 0.0722 * channel(5);
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

describe("colours", () => {
  const light = block(tokens, ":root {");
  const dark = { ...light, ...block(tokens, ':root[data-theme="dark"]') };

  it.each([
    ["light", light],
    ["dark", dark],
  ])("keep text readable in the %s theme (4.5:1)", (_name, theme) => {
    for (const [text, background] of PAIRS) {
      const fg = theme[text];
      const bg = theme[background];
      expect(fg && bg, `${text} / ${background}`).toBeTruthy();
      expect(
        contrast(fg as string, bg as string),
        `${text} on ${background}`,
      ).toBeGreaterThanOrEqual(4.5);
    }
  });
});
