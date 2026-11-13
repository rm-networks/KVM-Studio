import ts from "typescript";
import { describe, expect, it } from "vitest";

import { APP_NAME } from "../brand";
import en from "./en.json";
import fr from "./fr.json";

type Tree = { [key: string]: string | Tree };

function flatten(tree: Tree, prefix = ""): Map<string, string> {
  const out = new Map<string, string>();
  for (const [key, value] of Object.entries(tree)) {
    if (typeof value === "string") out.set(prefix + key, value);
    else for (const [k, v] of flatten(value, `${prefix}${key}.`)) out.set(k, v);
  }
  return out;
}

const variables = (text: string) => [...text.matchAll(/\{\{\s*(\w+)/g)].map((m) => m[1]).sort();

// Terms that read the same in every language.
const UNTRANSLATED = new Set([
  "BIOS",
  "Documentation",
  "CD/DVD",
  "English",
  "Français",
  "IDE",
  "Intel e1000e",
  "Linux",
  "NVMe",
  "Realtek RTL8139",
  "Secure Boot",
  "TPM 2.0",
  "SATA",
  "SCSI (virtio-scsi)",
  "UEFI",
  "VirtIO",
  "Windows",
  "vmxnet3",
]);
const TEXT_PROPS = new Set(["title", "aria-label", "placeholder", "alt", "label"]);

// Every source file but tests, as text.
const sources = import.meta.glob<string>(
  ["../**/*.ts", "../**/*.tsx", "!../**/*.test.*", "!../**/*.d.ts", "!../test/**"],
  { query: "?raw", import: "default", eager: true },
);

/** Visible text written in the code instead of the catalog, and t() keys missing from it. */
function scan(path: string, text: string, keys: Set<string>): string[] {
  const file = ts.createSourceFile(path, text, ts.ScriptTarget.Latest, true);
  const problems: string[] = [];
  const where = (node: ts.Node) =>
    `${path}:${file.getLineAndCharacterOfPosition(node.getStart()).line + 1}`;
  // Example paths in placeholders are not text either.
  const visible = (text: string) =>
    /\p{L}{2,}/u.test(text) && !UNTRANSLATED.has(text.trim()) && !text.startsWith("/");

  const visit = (node: ts.Node) => {
    if (ts.isJsxText(node) && visible(node.text)) {
      problems.push(`${where(node)} text "${node.text.trim()}"`);
    }
    if (ts.isJsxAttribute(node) && TEXT_PROPS.has(node.name.getText(file))) {
      const value = node.initializer;
      const literal =
        value && ts.isStringLiteral(value)
          ? value
          : value &&
              ts.isJsxExpression(value) &&
              value.expression &&
              ts.isStringLiteral(value.expression)
            ? value.expression
            : undefined;
      if (literal && visible(literal.text)) {
        problems.push(`${where(node)} ${node.name.getText(file)}="${literal.text}"`);
      }
    }
    if (
      ts.isCallExpression(node) &&
      ts.isIdentifier(node.expression) &&
      node.expression.text === "t" &&
      node.arguments[0] &&
      ts.isStringLiteral(node.arguments[0]) &&
      !keys.has(node.arguments[0].text)
    ) {
      problems.push(`${where(node)} unknown key ${node.arguments[0].text}`);
    }
    ts.forEachChild(node, visit);
  };
  visit(file);
  return problems;
}

describe("translations", () => {
  const english = flatten(en);
  const french = flatten(fr);

  it("have the same keys and variables in every language", () => {
    expect([...french.keys()].filter((k) => !english.has(k))).toEqual([]);
    expect([...english.keys()].filter((k) => !french.has(k))).toEqual([]);
    for (const [key, text] of english) {
      expect(variables(french.get(key) ?? ""), key).toEqual(variables(text));
    }
  });

  it("never spell out the product name", () => {
    for (const [key, text] of [...english, ...french]) expect(text, key).not.toContain(APP_NAME);
  });

  it("hold all the visible text", () => {
    const keys = new Set(english.keys());
    // Plural forms: t("x", { count }) reads x_one, x_other.
    for (const key of english.keys()) keys.add(key.replace(/_(one|other)$/, ""));
    const files = Object.entries(sources);
    expect(files.length).toBeGreaterThan(50);
    expect(files.flatMap(([path, text]) => scan(path, text, keys))).toEqual([]);
  });
});
