// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { ComponentType, ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { act, render as testingRender, screen } from "@testing-library/react";
import { TooltipProvider } from "@/components/ui/tooltip";
import { MarkdownText } from "@/app/newchat/ui/markdown-text";
import { Reasoning } from "@/app/newchat/ui/reasoning";

const fixture = vi.hoisted(() => ({
  part: { type: "text", text: "", status: { type: "complete" } },
  listeners: new Set<() => void>(),
}));

const render = (ui: ReactNode) =>
  testingRender(ui, {
    wrapper: ({ children }) => <TooltipProvider>{children}</TooltipProvider>,
  });

// Keep the real assistant-ui Markdown renderer; replace only its runtime state.
vi.mock("@assistant-ui/react", async () => {
  const { useSyncExternalStore } = await import("react");
  const usePart = () =>
    useSyncExternalStore(
      (listener) => {
        fixture.listeners.add(listener);
        return () => {
          fixture.listeners.delete(listener);
        };
      },
      () => fixture.part
    );
  return {
    useAuiState: (selector: (state: unknown) => unknown) =>
      selector({ part: usePart(), message: { id: "math-test", content: [] } }),
    useMessagePartText: usePart,
    INTERNAL: {
      useSmooth: (part: unknown) => part,
      useSmoothStatus: () => fixture.part.status,
      withSmoothContextProvider: (component: ComponentType) => component,
    },
  };
});
vi.mock("react-i18next", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-i18next")>()),
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/app/newchat/ui/message-sources", () => ({
  useMessageSources: () => ({
    messageId: "math-test",
    content: [],
    sources: [],
    images: [],
    displayIndices: new Map(),
  }),
  findMessageSource: () => undefined,
}));
vi.mock("@/app/newchat/ui/sources-panel-context", () => ({
  useSourcesPanelActions: () => ({ open: vi.fn() }),
}));
vi.mock("@/app/newchat/ui/sources-panel", () => ({
  getCitationKey: () => "a1",
  getCitationLabel: () => "Source",
}));
vi.mock("@/app/newchat/ui/cite-marker", () => ({
  CiteMarker: ({ citekey }: { citekey: string }) => (
    <sup data-testid="citation">{citekey}</sup>
  ),
}));
vi.mock("@/app/newchat/adapter/remote-chat-model-adapter", () => ({
  searchImagesRegistry: new Map(),
}));
vi.mock("@/services/storageService", () => ({
  getLocalFileDownloadUrl: (url: string) => url,
  isLocalStorageObjectUrl: () => false,
}));
vi.mock("@/app/newchat/ui/authenticated-image", () => ({
  AuthenticatedImage: () => <span data-testid="image" />,
}));
vi.mock("@/app/newchat/ui/shiki-highlighter", () => ({
  SyntaxHighlighter: ({ code }: { code: string }) => <code>{code}</code>,
}));
vi.mock("@/app/newchat/ui/mermaid-diagram", () => ({
  MermaidDiagram: ({ code }: { code: string }) => (
    <div data-testid="mermaid">{code}</div>
  ),
}));

beforeEach(() => {
  fixture.part = { type: "text", text: "", status: { type: "complete" } };
});

it.each([
  String.raw`$\sin\theta = \dfrac{\text{对边}}{\text{斜边}}$`,
  String.raw`$$\sin^2\theta + \cos^2\theta = 1$$`,
  String.raw`\(\frac{1}{2}\)`,
  String.raw`\[\cos 2\theta = 1-2\sin^2\theta\]`,
  "$$\n\\frac{1}{2}\n$$",
])("renders real answer math: %s", (text) => {
  fixture.part.text = text;
  const { container } = render(<MarkdownText />);
  expect(container.querySelector(".katex")).not.toBeNull();
  expect(container.querySelector("math")).not.toBeNull();
  expect(container.querySelector(".katex-error")).toBeNull();
});

it("renders every same-line formula and formulas in table cells", () => {
  fixture.part.text = String.raw`$$\sin 2\theta=2\sin\theta\cos\theta$$ $$\cos 2\theta=1-2\sin^2\theta$$

| Angle | Value |
| --- | --- |
| $\theta$ | $\frac{\sqrt{2}}{2}$ |`;
  const { container } = render(<MarkdownText />);
  expect(container.querySelectorAll(".katex")).toHaveLength(4);
  expect(container.querySelectorAll(".katex-display")).toHaveLength(2);
  expect(container.querySelectorAll("td .katex")).toHaveLength(2);
});

it("keeps single-dollar math inline and math fences in display mode", () => {
  fixture.part.text = ["Inline $x^2$.", "", "```math", "y=x^2", "```"].join(
    "\n"
  );
  const { container } = render(<MarkdownText />);
  expect(container.querySelectorAll(".katex")).toHaveLength(2);
  expect(container.querySelectorAll(".katex-display")).toHaveLength(1);
});

it.each(["running", "complete"] as const)(
  "renders reasoning math in %s state",
  (status) => {
    fixture.part = {
      type: "reasoning",
      text: String.raw`$\sin\theta$ and \[\frac{1}{2}\]`,
      status: { type: status },
    };
    const { container } = render(
      <Reasoning
        type="reasoning"
        text={fixture.part.text}
        status={{ type: status }}
      />
    );
    expect(container.querySelectorAll(".katex")).toHaveLength(2);
  }
);

it("tolerates partial and invalid formulas without losing nearby text", () => {
  fixture.part.text = String.raw`Before $\frac{1}{`;
  const { container } = render(<MarkdownText />);
  expect(container.textContent).toContain("Before");
  act(() => {
    fixture.part = {
      ...fixture.part,
      text: String.raw`Before $\frac{1}{2}$ After`,
    };
    fixture.listeners.forEach((listener) => listener());
  });
  expect(container.querySelector(".katex")).not.toBeNull();
  act(() => {
    fixture.part = {
      ...fixture.part,
      text: String.raw`Before $\frac{1}$ After`,
    };
    fixture.listeners.forEach((listener) => listener());
  });
  expect(container.textContent).toContain("Before");
  expect(container.textContent).toContain("After");
  expect(container.querySelector(".katex-error")).not.toBeNull();
});

it("preserves literal formulas inside code and ordinary currency", () => {
  fixture.part.text = [
    "Prices: $20 and $30.",
    "",
    String.raw`Inline code: \`$\sin\theta$\` and \`\(x\)\`.`,
    "",
    "```text",
    String.raw`$\frac{1}{2}$ and \(x\)`,
    "```",
  ]
    .join("\n")
    .replaceAll("\\`", "`");
  const { container } = render(<MarkdownText />);
  expect(container.querySelector(".katex")).toBeNull();
  expect(container.textContent).toContain("$20 and $30");
  expect(container.textContent).toContain(String.raw`$\frac{1}{2}$ and \(x\)`);
});

it("preserves common Markdown, citations, images and Mermaid dispatch", () => {
  fixture.part.text = [
    "# Heading",
    "",
    "**Bold** and *italic* and ~~plain deletion~~.",
    "",
    "> Quote",
    "",
    "1. Ordered",
    "",
    "- [x] Done",
    "- [ ] Pending",
    "",
    "[Link](https://example.com)",
    "",
    "![Image](https://example.com/a.png)",
    "",
    "Reference [[a1]]",
    "",
    "---",
    "",
    "```mermaid",
    "graph LR; A-->B",
    "```",
  ].join("\n");
  const { container } = render(<MarkdownText />);
  expect(screen.getByRole("heading", { name: "Heading" })).toBeInTheDocument();
  expect(container.querySelector("strong")).toHaveTextContent("Bold");
  expect(container.querySelector("em")).toHaveTextContent("italic");
  expect(container.querySelector("blockquote")).toHaveTextContent("Quote");
  expect(container.querySelector("ol li")).toHaveTextContent("Ordered");
  expect(screen.getAllByRole("checkbox")).toHaveLength(2);
  expect(screen.getByRole("link")).toHaveAttribute(
    "href",
    "https://example.com"
  );
  expect(screen.getByTestId("citation")).toHaveTextContent("a1");
  expect(screen.getByTestId("image")).toBeInTheDocument();
  expect(screen.getByTestId("mermaid")).toHaveTextContent("graph LR; A-->B");
  expect(container.querySelector("hr")).not.toBeNull();
  expect(container.querySelector("del")).toBeNull();
  expect(container.textContent).toContain("plain deletion");
});
