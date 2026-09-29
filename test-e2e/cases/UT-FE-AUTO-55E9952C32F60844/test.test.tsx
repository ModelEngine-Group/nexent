import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render } from "@testing-library/react";
import type { AgentStep, ChatMessageType } from "@/types/chat";

import { upsertHistorySummaryInMessages } from "@/app/[locale]/chat/streaming/chatStreamHandler";
import { TaskWindow } from "@/app/[locale]/chat/streaming/taskWindow";

vi.mock("@/app/i18n", () => ({ resourcesCustom: undefined }));

vi.mock("@/lib/logger", () => ({
  default: {
    debug: () => {},
    info: () => {},
    warn: () => {},
    error: () => {},
    log: () => {},
  },
}));

vi.mock("react-i18next", () => {
  const t = (key: string, options?: Record<string, unknown>) => {
    if (key === "taskWindow.historySummary.coveredThrough") {
      return `covered-through-${String(options?.id)}`;
    }
    if (key.startsWith("taskWindow.historySummary.triggers.")) {
      return typeof options?.defaultValue === "string"
        ? options.defaultValue
        : key;
    }
    if (key === "taskWindow.historySummary.trigger") {
      return `trigger:${String(options?.trigger ?? "")}`;
    }
    if (key === "taskWindow.historySummary.title") return "History Summary";
    if (key === "taskWindow.historySummary.compacting")
      return "Compacting history summary...";
    if (key === "taskWindow.historySummary.empty") return "No summary available";
    if (key === "taskWindow.historySummary.triggerUnknown")
      return "unknown trigger";
    return key;
  };
  return {
    useTranslation: () => ({
      t,
      i18n: { language: "zh", resolvedLanguage: "zh" },
    }),
  };
});

vi.mock("@/hooks/useConfig", () => ({
  useConfig: () => ({ appConfig: undefined }),
}));

vi.mock("@/services/storageService", () => ({
  storageService: {},
  extractObjectNameFromUrl: () => undefined,
}));

vi.mock("@/components/ui/scrollArea", () => ({
  ScrollArea: (props: any) =>
    React.createElement("div", { className: props.className }, props.children),
}));

vi.mock("@/components/common/markdownRenderer", () => ({
  MarkdownRenderer: (props: any) =>
    React.createElement("span", { "data-testid": "markdown" }, props.content),
  CodeBlock: () => null,
}));

vi.mock("antd", () => ({
  Button: (props: any) =>
    React.createElement("button", { type: "button" }, props.children),
  message: { error: () => {}, success: () => {} },
}));

vi.mock("lucide-react", () => {
  const icon = (name: string) => (props: any) =>
    React.createElement("svg", {
      "data-icon": name,
      className: props.className,
    });
  return {
    Globe: icon("Globe"),
    Search: icon("Search"),
    Zap: icon("Zap"),
    Bot: icon("Bot"),
    Code: icon("Code"),
    FileText: icon("FileText"),
    ChevronRight: icon("ChevronRight"),
    Wrench: icon("Wrench"),
    CheckCircle2: icon("CheckCircle2"),
    AlertTriangle: icon("AlertTriangle"),
    RotateCcw: icon("RotateCcw"),
    ShieldCheck: icon("ShieldCheck"),
    LoaderCircle: icon("LoaderCircle"),
  };
});

afterEach(cleanup);

const userMessage = (): ChatMessageType => ({
  id: "u-1",
  role: "user",
  content: "hello",
});

const assistantMessage = (
  overrides: Partial<ChatMessageType> = {}
): ChatMessageType => ({
  id: "a-1",
  role: "assistant",
  content: "",
  steps: [],
  ...overrides,
});

const buildStep = (id: string, content = ""): AgentStep => ({
  id,
  title: "History Summary",
  content,
  expanded: true,
  contents: [],
  metrics: null,
  thinking: { content: "", expanded: true },
  code: { content: "", expanded: true },
  output: { content: "", expanded: true },
});

describe("upsertHistorySummaryInMessages", () => {
  it("UT-FE-AUTO-55E9952C32F60844 compacting adds a transient history-summary step to the last assistant message", () => {
    const messages = [
      userMessage(),
      assistantMessage({ id: "a-1", message_id: 1 }),
    ];
    const result = upsertHistorySummaryInMessages(
      messages,
      JSON.stringify({ status: "compacting" })
    );

    const last = result[result.length - 1];
    expect(last.role).toBe("assistant");
    const transient = (last.steps ?? []).find(
      (s) => s.id === "history-summary-compacting"
    );
    expect(transient).toBeDefined();
    expect(transient?.title).toBe("History Summary");
    expect(transient?.contents?.[0]?.type).toBe("history_summary");
  });

  it("accepted with numeric covered_through_message_id persists a summary step on the covered message", () => {
    const messages = [
      assistantMessage({ id: "a-5", message_id: 5 }),
      assistantMessage({ id: "a-6", message_id: 6 }),
    ];
    const result = upsertHistorySummaryInMessages(
      messages,
      JSON.stringify({ status: "accepted", covered_through_message_id: 5 })
    );

    const covered = result.find((m) => m.message_id === 5);
    expect((covered?.steps ?? []).some((s) => s.id === "history-summary-5")).toBe(
      true
    );
    for (const m of result) {
      expect(
        (m.steps ?? []).some((s) => s.id === "history-summary-compacting")
      ).toBe(false);
    }
  });

  it("accepted replaces an existing persistent summary step instead of appending", () => {
    const messages = [
      assistantMessage({
        id: "a-5",
        message_id: 5,
        steps: [buildStep("history-summary-5", "old")],
      }),
    ];
    const result = upsertHistorySummaryInMessages(
      messages,
      JSON.stringify({ status: "accepted", covered_through_message_id: 5 })
    );

    const covered = result.find((m) => m.message_id === 5);
    const matching = (covered?.steps ?? []).filter(
      (s) => s.id === "history-summary-5"
    );
    expect(matching).toHaveLength(1);
    expect(matching[0].content).toBe("");
  });

  it("idle removes only the transient step and leaves persistent steps untouched", () => {
    const messages = [
      assistantMessage({
        id: "a-5",
        message_id: 5,
        steps: [
          buildStep("history-summary-compacting"),
          buildStep("history-summary-5", "keep"),
        ],
      }),
    ];
    const result = upsertHistorySummaryInMessages(
      messages,
      JSON.stringify({ status: "idle" })
    );

    const covered = result.find((m) => m.message_id === 5);
    const steps = covered?.steps ?? [];
    expect(steps.some((s) => s.id === "history-summary-compacting")).toBe(false);
    expect(steps.some((s) => s.id === "history-summary-5")).toBe(true);
    expect(steps).toHaveLength(1);
  });

  it("invalid JSON returns the original messages array unchanged without throwing", () => {
    const messages = [assistantMessage({ id: "a-1", message_id: 1 })];
    let result: ChatMessageType[] | undefined;

    expect(() => {
      result = upsertHistorySummaryInMessages(messages, "not valid json {{{");
    }).not.toThrow();

    expect(result).toBe(messages);
  });

  it("does not expose plaintext secrets in the result", () => {
    const messages = [assistantMessage({ id: "a-5", message_id: 5 })];
    const result = upsertHistorySummaryInMessages(
      messages,
      JSON.stringify({
        status: "accepted",
        covered_through_message_id: 5,
        summary: "final summary",
      })
    );

    const serialized = JSON.stringify(result);
    expect(serialized).not.toMatch(/sk-[A-Za-z0-9]{16,}/);
    expect(serialized.toLowerCase()).not.toContain("api_key");
    expect(serialized.toLowerCase()).not.toContain("password");
  });
});

describe("HistorySummaryEvent (via TaskWindow)", () => {
  const renderHistorySummary = (content: unknown) => {
    const message = {
      id: "hs-1",
      role: "assistant" as const,
      content:
        typeof content === "string" ? content : JSON.stringify(content),
      type: "history_summary",
      timestamp: new Date(),
    };
    return render(<TaskWindow messages={[message]} />);
  };

  it("compacting renders loading animation and text without summary body", () => {
    const { container } = renderHistorySummary({ status: "compacting" });

    expect(container.querySelector("svg.animate-spin")).toBeTruthy();
    expect(container.textContent).toContain("Compacting history summary...");
    expect(container.textContent).not.toContain("History Summary");
    expect(container.querySelector('[data-testid="markdown"]')).toBeNull();
  });

  it("accepted renders title, covered_through, trigger and final string summary", () => {
    const { container } = renderHistorySummary({
      status: "accepted",
      covered_through_message_id: 42,
      trigger: "context_overflow",
      summary: "This is the final summary text",
    });

    expect(container.textContent).toContain("History Summary");
    expect(container.textContent).toContain("covered-through-42");
    expect(container.textContent).toContain("trigger:context_overflow");
    expect(
      container.querySelector('[data-testid="markdown"]')?.textContent
    ).toContain("This is the final summary text");
  });

  it("accepted renders an object summary as formatted markdown", () => {
    const { container } = renderHistorySummary({
      status: "accepted",
      covered_through_message_id: 7,
      summary: { key_point: "value one", second_key: "value two" },
    });

    const markdown =
      container.querySelector('[data-testid="markdown"]')?.textContent ?? "";
    expect(markdown).toContain("key point");
    expect(markdown).toContain("value one");
    expect(markdown).toContain("second key");
    expect(markdown).toContain("value two");
  });
});
