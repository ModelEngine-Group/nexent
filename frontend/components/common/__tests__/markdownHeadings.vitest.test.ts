import { describe, expect, it } from "vitest";

import {
  extractMarkdownHeadings,
  normalizeMarkdownHeadingText,
} from "../markdownHeadings";

describe("markdown heading projection", () => {
  it("extracts visible headings and assigns stable duplicate IDs", () => {
    expect(
      extractMarkdownHeadings("# Overview\n## Details\n# Overview")
    ).toEqual([
      { id: "overview", level: 1, text: "Overview" },
      { id: "details", level: 2, text: "Details" },
      { id: "overview-1", level: 1, text: "Overview" },
    ]);
  });

  it("normalizes inline markdown before creating labels", () => {
    expect(normalizeMarkdownHeadingText(" **Build** `Agent` ")).toBe(
      "Build Agent"
    );
  });
});
