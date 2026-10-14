import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render } from "@testing-library/react";
import {
  AssistantRuntimeProvider,
  useExternalStoreRuntime,
} from "@assistant-ui/react";
import {
  collectStream,
  restoreHistory,
  summaryEvent,
  summaryParts,
} from "../../infra/automation/d1/frontend/newchat-fixture";
import { ReadOnlyConversation } from "@/app/newchat/assistant-ui/thread";

vi.mock("@/app/i18n", () => ({ resourcesCustom: {} }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: any) =>
      key === "taskWindow.historySummary.coveredThrough"
        ? `covered-through-${options.id}`
        : key,
    i18n: { language: "en", resolvedLanguage: "en" },
  }),
}));

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => {
      throw new Error("Unexpected external request");
    }),
  );
});
afterEach(() => {
  cleanup();
  expect(fetch).not.toHaveBeenCalled();
  vi.unstubAllGlobals();
});

function SummaryConversation({ content }: { content: any[] }) {
  const runtime = useExternalStoreRuntime({
    messages: [
      {
        id: "summary",
        role: "assistant" as const,
        content,
        createdAt: new Date(),
        status: { type: "complete" as const, reason: "stop" as const },
      },
    ],
    isRunning: false,
    onNew: async () => {},
    convertMessage: (message: any) => message,
  });
  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <ReadOnlyConversation
        agent={{ agent_id: 1, name: "fixture" } as any}
        title="History"
      />
    </AssistantRuntimeProvider>
  );
}

describe("UT-FE-AUTO-55E9952C32F60844 newchat history summaries", () => {
  it("UT-FE-AUTO-55E9952C32F60844 compacting adds one transient summary and renders a spinner without body", async () => {
    const results = await collectStream([
      summaryEvent({ status: "compacting" }),
      summaryEvent({ status: "compacting" }),
    ]);
    const parts = summaryParts(results.at(-1));
    expect(parts).toEqual([
      { type: "data", name: "history-summary", data: { status: "compacting" } },
    ]);
    const { container } = render(<SummaryConversation content={parts} />);
    expect(container.querySelector("svg.animate-spin")).toBeTruthy();
    expect(container.textContent).toContain(
      "taskWindow.historySummary.compacting",
    );
    expect(container.querySelector("details")).toBeNull();
  });

  it("accepted replaces compacting and repeated summaries without duplication", async () => {
    const results = await collectStream([
      summaryEvent({ status: "compacting" }),
      summaryEvent({
        status: "accepted",
        covered_through_message_id: 5,
        summary: "old",
      }),
      summaryEvent({
        status: "accepted",
        covered_through_message_id: 5,
        summary: "final summary",
      }),
    ]);
    expect(summaryParts(results[0])[0].data.status).toBe("compacting");
    expect(summaryParts(results.at(-1))).toHaveLength(1);
    expect(summaryParts(results.at(-1))[0].data).toEqual({
      status: "accepted",
      covered_through_message_id: 5,
      summary: "final summary",
    });
    expect(JSON.stringify(results.at(-1))).not.toContain('"old"');
    const { container } = render(
      <SummaryConversation content={summaryParts(results.at(-1))} />,
    );
    expect(container.textContent).toContain("taskWindow.historySummary.title");
    expect(container.textContent).toContain("covered-through-5");
    expect(container.textContent).toContain("final summary");
    expect(container.querySelector("details")?.hasAttribute("open")).toBe(
      false,
    );
  });

  it("idle removes only the current summary and preserves ordinary content", async () => {
    const results = await collectStream([
      { type: "final_answer", content: "keep answer" },
      summaryEvent({ status: "compacting" }),
      summaryEvent({ status: "idle" }),
    ]);
    expect(summaryParts(results.at(-1))).toEqual([]);
    expect(results.at(-1).content).toContainEqual(
      expect.objectContaining({ type: "text", text: "keep answer" }),
    );
  });

  it("invalid JSON and unsupported status leave an accepted summary unchanged", async () => {
    const results = await collectStream([
      summaryEvent({
        status: "accepted",
        covered_through_message_id: 5,
        summary: "keep",
      }),
      { type: "history_summary", content: "not valid json {{{" },
      summaryEvent({ status: "unknown" }),
    ]);
    expect(summaryParts(results.at(-1))).toEqual(summaryParts(results[0]));
  });

  it.each(["final summary", { markdown: "# final summary" }])(
    "restores and renders persisted string or markdown-object summaries: %j",
    async (summary) => {
      const history = await restoreHistory([
        {
          message_id: 5,
          role: "assistant",
          message: [
            summaryEvent({
              status: "accepted",
              covered_through_message_id: 5,
              summary,
            }),
          ],
        },
      ]);
      const content = history.messages[0].message.content as any[];
      expect(content).toContainEqual({
        type: "data",
        name: "history-summary",
        data: { status: "accepted", covered_through_message_id: 5, summary },
      });
      const { container } = render(<SummaryConversation content={content} />);
      expect(container.textContent).toContain("final summary");
      expect(container.textContent).toContain("covered-through-5");
      expect(container.textContent).not.toMatch(
        /sk-[A-Za-z0-9]{16,}|api_key|password/i,
      );
    },
  );
});
