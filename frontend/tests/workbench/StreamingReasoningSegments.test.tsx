// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";
import type { ReactNode } from "react";

// Records every markdown parse triggered by the components under test. The
// regression assertions below fail if the streaming render is reverted to a
// single full-text ReactMarkdown, because then every streamed chunk would
// re-parse the sealed prefix too.
const markdownRenders = vi.hoisted(() => [] as string[]);

vi.mock("react-markdown", () => ({
  default: ({ children }: { children?: ReactNode }) => {
    const content = String(children ?? "");
    markdownRenders.push(content);
    return <div data-testid="streaming-md">{content}</div>;
  },
}));

// react-shiki's dist CSS cannot be loaded by Node when vitest externalizes
// node_modules. The syntax highlighter is irrelevant to the streaming path
// under test, so stub the module that pulls it in.
vi.mock("@/app/newchat/ui/shiki-highlighter", () => ({
  SyntaxHighlighter: () => null,
}));

import { StreamingReasoningSegments } from "@/app/newchat/ui/reasoning";
import { splitStreamingMarkdown } from "@/app/newchat/ui/streaming-markdown-split";

beforeEach(() => {
  markdownRenders.length = 0;
});

describe("splitStreamingMarkdown", () => {
  it("returns no segments for empty text", () => {
    expect(splitStreamingMarkdown("")).toEqual([]);
  });

  it("keeps segments concatenated to the exact source text", () => {
    const samples = [
      "single line",
      "a\n\nb\n\nc",
      "intro text\n\n```python\ncode line 1\n\ncode line 2\n```\n\noutro text",
      "x".repeat(600),
      Array.from({ length: 30 }, (_, i) => `line-${i} content`).join("\n"),
      "crlf line one\r\n\r\ncrlf line two\r\n",
      "> quote\n\n- item\n  - nested\n\ntail",
    ];
    for (const text of samples) {
      const segments = splitStreamingMarkdown(text, {
        minSegmentLength: 50,
        maxTailLength: 300,
      });
      expect(segments.join("")).toBe(text);
      expect(segments.length).toBeGreaterThan(0);
    }
  });

  it("seals at blank lines once the minimum length is reached", () => {
    const text = "para one\n\npara two\n\npara three";
    expect(
      splitStreamingMarkdown(text, { minSegmentLength: 8, maxTailLength: 1000 })
    ).toEqual(["para one\n\n", "para two\n\n", "para three"]);
    // Below the minimum everything stays in the active tail.
    expect(
      splitStreamingMarkdown(text, {
        minSegmentLength: 50,
        maxTailLength: 1000,
      })
    ).toEqual([text]);
  });

  it("never splits inside fenced code blocks", () => {
    const text =
      "intro text\n\n```python\ncode line 1\n\ncode line 2\n```\n\noutro text";
    const segments = splitStreamingMarkdown(text, {
      minSegmentLength: 1,
      maxTailLength: 1000,
    });
    expect(segments).toEqual([
      "intro text\n\n",
      "```python\ncode line 1\n\ncode line 2\n```\n\n",
      "outro text",
    ]);
  });

  it("falls back to line breaks when the tail exceeds maxTailLength", () => {
    const lines = Array.from(
      { length: 12 },
      (_, i) => `line-${String(i).padStart(2, "0")}-${"x".repeat(20)}`
    );
    const text = lines.join("\n");
    const segments = splitStreamingMarkdown(text, {
      minSegmentLength: 4000,
      maxTailLength: 100,
    });
    expect(segments.join("")).toBe(text);
    expect(segments.length).toBeGreaterThan(1);
    for (const segment of segments.slice(0, -1)) {
      expect(segment.length).toBeLessThanOrEqual(200);
      expect(segment.endsWith("\n")).toBe(true);
    }
  });

  it("splits whitespace in a single-line tail longer than maxTailLength", () => {
    const text = Array.from({ length: 120 }, (_, i) => `word${i}`).join(" ");
    const segments = splitStreamingMarkdown(text, {
      minSegmentLength: 4000,
      maxTailLength: 150,
    });
    expect(segments.join("")).toBe(text);
    expect(segments.length).toBeGreaterThan(1);
    for (const segment of segments.slice(0, -1)) {
      expect(segment.length).toBeLessThanOrEqual(150);
      expect(segment.endsWith(" ")).toBe(true);
    }
  });

  it("keeps unsplittable input as a single segment", () => {
    // No line break and no whitespace: degrade to the legacy single-segment
    // cost instead of crashing or inventing a split point.
    const text = "x".repeat(400);
    expect(
      splitStreamingMarkdown(text, {
        minSegmentLength: 4000,
        maxTailLength: 100,
      })
    ).toEqual([text]);
  });

  it("keeps sealed segments byte-identical while the text grows", () => {
    const paragraphs = [
      "alpha reasoning about the minimal covering set for resources. ".repeat(
        3
      ) + "\n\n",
      "beta the candidate list includes a search tool and a file reader. ".repeat(
        3
      ) + "\n\n",
      "gamma check the fence handling. \n\n```code\ninside the fence\nno blank sealing here\n```\n\n",
      "delta final tail that never receives a blank line while streaming. ".repeat(
        2
      ),
    ];
    // Stream every paragraph in small pieces to simulate token chunks,
    // including pieces that do not complete a paragraph.
    const chunks: string[] = [];
    for (const paragraph of paragraphs) {
      for (let i = 0; i < paragraph.length; i += 40) {
        chunks.push(paragraph.slice(i, i + 40));
      }
    }

    let text = "";
    let previousSealed: string[] = [];
    for (const chunk of chunks) {
      text += chunk;
      const segments = splitStreamingMarkdown(text, {
        minSegmentLength: 50,
        maxTailLength: 500,
      });
      expect(segments.join("")).toBe(text);
      const sealed = segments.slice(0, -1);
      // Append-stability: previously sealed segments never change, which is
      // what keeps the memoized prefix from re-parsing.
      expect(sealed.slice(0, previousSealed.length)).toEqual(previousSealed);
      previousSealed = sealed;
    }
    expect(previousSealed.length).toBeGreaterThan(0);
  });
});

describe("StreamingReasoningSegments", () => {
  const mdPara = (marker: string) =>
    `${marker} ${"deliberating about the minimal covering set of candidate resources. ".repeat(10)}\n\n`;
  const p1 = mdPara("MARK-P1");
  const p2 = mdPara("MARK-P2");
  const p3 = mdPara("MARK-P3");
  const head = p1 + p2 + p3;
  const tail1 = "MARK-P4 the first line of the still streaming tail.\n";
  const tail2 = "MARK-P4 a second line appended by the next chunk.\n";

  it("re-parses only the active tail on each streamed chunk", () => {
    const { rerender } = render(
      <StreamingReasoningSegments text={head + tail1} />
    );
    // Three sealed paragraphs plus the active tail.
    expect(markdownRenders).toHaveLength(4);
    expect(
      markdownRenders.filter((rendered) => rendered.includes("MARK-P1"))
    ).toHaveLength(1);

    rerender(<StreamingReasoningSegments text={head + tail1 + tail2} />);
    // Exactly one additional parse: the grown tail. The sealed prefix is
    // not re-parsed, which is the fix for the quadratic streaming cost.
    expect(markdownRenders).toHaveLength(5);
    const lastRender = markdownRenders[markdownRenders.length - 1];
    expect(lastRender).toContain("MARK-P4");
    expect(lastRender).not.toContain("MARK-P1");
    expect(
      markdownRenders.filter((rendered) => rendered.includes("MARK-P1"))
    ).toHaveLength(1);
  });

  it("renders the full text content", () => {
    const { container } = render(
      <StreamingReasoningSegments text={head + tail1} />
    );
    expect(container.textContent).toBe(head + tail1);
  });

  it("renders empty text without mounting markdown", () => {
    const { container } = render(<StreamingReasoningSegments text="" />);
    expect(container.textContent).toBe("");
    expect(markdownRenders).toHaveLength(0);
  });

  it("keeps an unclosed trailing code fence in the tail without crashing", () => {
    const text = p1 + "```python\nprint('still streaming')\n";
    const { container } = render(<StreamingReasoningSegments text={text} />);
    expect(container.textContent).toBe(text);
    expect(
      markdownRenders.filter((rendered) => rendered.includes("MARK-P1"))
    ).toHaveLength(1);
  });
});
