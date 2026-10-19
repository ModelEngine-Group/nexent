// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

// Regression tests for streaming parts index stability (bug record:
// STREAM-PARTS-INDEX-REORDER-20261019).
//
// @assistant-ui's MessagePrimitive.GroupedParts derives React keys for
// non-tool parts from the part's array index (``part-${index}``). The adapter
// used to reorder the yielded parts array on every stream chunk:
// collapseSubAgentParts moved later parts of a sub-agent run back to the
// run's first-occurrence position, and the history-summary "idle" event
// spliced its card out of the middle of the array. Every reorder changed the
// index-derived keys of all following parts and remounted their subtrees;
// each remounted Radix Presence ref fires a nested setState during commit
// (``setNode``), and long multi-step NL2Agent runs accumulated 50+ nested
// updates, crashing the page with React minified error #185 ("Maximum update
// depth exceeded") through the root global-error boundary.
//
// The invariant pinned here: across consecutive stream yields, the identity
// of the part at every already-emitted index never changes — parts are only
// appended or replaced in place, never reordered or removed.

import { expect, it, vi } from "vitest";
import type {
  ChatModelRunOptions,
  ChatModelRunResult,
} from "@assistant-ui/react";
import { ReadableStream } from "node:stream/web";

const runAgent = vi.hoisted(() => vi.fn());
vi.mock("@/services/conversationService", () => ({
  conversationService: { runAgent },
}));
vi.mock("@/lib/logger", () => ({
  default: { log: vi.fn(), warn: vi.fn(), error: vi.fn() },
}));

import { remoteChatModelAdapter } from "@/app/newchat/adapter/remote-chat-model-adapter";

type StreamEvent = Record<string, unknown> & { type: string; content: string };

/** Minimal structural view of the message parts the adapter yields. */
type StreamPart = {
  type?: string;
  name?: string;
  text?: string;
  metadata?: { runId?: string };
  data?: { status?: string; summary?: unknown };
  [key: string]: unknown;
};

/** Runs the adapter over a fake SSE event list and returns every yielded
 * parts snapshot, in yield order. */
async function collectYields(events: StreamEvent[]): Promise<StreamPart[][]> {
  runAgent.mockImplementationOnce(async () =>
    new ReadableStream<Uint8Array>({
      start(controller) {
        for (const event of events) {
          controller.enqueue(
            new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`)
          );
        }
        controller.close();
      },
    }).getReader()
  );
  const input = {
    messages: [
      {
        id: "question",
        role: "user",
        content: [{ type: "text", text: "创建数据分析智能体" }],
      },
    ],
    abortSignal: new AbortController().signal,
    context: {},
    runConfig: { custom: { runtimeMode: "nl2agent", agentId: 27 } },
    unstable_threadId: "local-nl2agent",
  } as unknown as ChatModelRunOptions;
  const run = remoteChatModelAdapter.run(input);
  const results: ChatModelRunResult[] = [];
  if (Symbol.asyncIterator in run) {
    for await (const result of run) results.push(result);
  } else {
    results.push(await run);
  }
  return results.map((result) => result.content as StreamPart[]);
}

/** Stable per-index identity: type + data name + sub-agent runId. Text grows
 * in place and step labels can be prepended to an existing part, so text
 * content is intentionally excluded from the identity. */
function identityAt(content: StreamPart[], index: number): string | undefined {
  const part = content[index];
  if (!part) return undefined;
  return `${part.type}|${part.name ?? ""}|${part.metadata?.runId ?? ""}`;
}

/** Asserts the no-shift invariant across all yields: the parts array only
 * grows, and every previously-emitted index keeps its identity. */
function assertIndexStable(yields: StreamPart[][]): void {
  expect(yields.length).toBeGreaterThan(0);
  const last = yields.at(-1)!;
  expect(last.length).toBeGreaterThan(0);
  for (let k = 1; k < yields.length; k++) {
    const previous = yields[k - 1];
    const current = yields[k];
    expect(
      current.length,
      `yield ${k} shrank the parts array from ${previous.length} to ${current.length} (a part was removed)`
    ).toBeGreaterThanOrEqual(previous.length);
    for (let i = 0; i < previous.length; i++) {
      expect(
        identityAt(current, i),
        `yield ${k} changed the part identity at index ${i} from "${identityAt(previous, i)}" (parts were reordered)`
      ).toBe(identityAt(previous, i));
    }
  }
}

it("never reorders already-emitted parts when parallel sub-agent output interleaves", async () => {
  const yields = await collectYields([
    // Parent reasoning streams first.
    { type: "model_output_thinking", content: "parent planning " },
    // Sub-agent R starts and streams reasoning.
    {
      type: "subagent_start",
      content: JSON.stringify({
        agent_id: 31,
        agent_name: "Researcher",
        task: "collect data",
        invocation_id: "inv-r",
      }),
    },
    {
      type: "model_output_thinking",
      content: "R thinking ",
      invocation_id: "inv-r",
    },
    // Parallel sub-agent S starts while R is still active.
    {
      type: "subagent_start",
      content: JSON.stringify({
        agent_id: 32,
        agent_name: "Analyst",
        task: "analyze data",
        invocation_id: "inv-s",
      }),
    },
    {
      type: "model_output_thinking",
      content: "S thinking ",
      invocation_id: "inv-s",
    },
    // Parent emits text between the sub-agent chunks.
    { type: "model_output", content: "parent note " },
    // R emits a tool call: a brand-new part for run R that arrives after S's
    // parts — the exact case the old collapse moved back beside R's group,
    // shifting every part in between.
    {
      type: "tool",
      content: "",
      tool_name: "search",
      tool_arguments: { query: "finance" },
      invocation_id: "inv-r",
    },
    // R keeps streaming reasoning (appends in place to R's existing part).
    {
      type: "model_output_thinking",
      content: "R more ",
      invocation_id: "inv-r",
    },
    // S emits a tool call too.
    {
      type: "tool",
      content: "",
      tool_name: "search",
      tool_arguments: { query: "risk" },
      invocation_id: "inv-s",
    },
    {
      type: "subagent_end",
      content: JSON.stringify({ invocation_id: "inv-r" }),
    },
    {
      type: "subagent_end",
      content: JSON.stringify({ invocation_id: "inv-s" }),
    },
    { type: "final_answer", content: "analysis complete" },
    { type: "done", content: "" },
  ]);
  assertIndexStable(yields);

  // R's late tool-call part must stay at the end in arrival order, after the
  // parent text and S's boundary — the old reordering moved it back before
  // them.
  const last = yields.at(-1)!;
  const parentTextIndex = last.findIndex(
    (part) => part.type === "text" && part.text === "parent note "
  );
  const sBoundaryIndex = last.findIndex(
    (part) =>
      part.name === "subagent-boundary" && part.metadata?.runId === "run-2"
  );
  const rToolIndex = last.findIndex(
    (part) => part.type === "tool-call" && part.metadata?.runId === "run-1"
  );
  expect(parentTextIndex).toBeGreaterThanOrEqual(0);
  // Arrival order: S's boundary precedes the parent text, and R's late
  // tool-call part lands at the end, after the parent text — with the old
  // reordering it was moved back before both.
  expect(sBoundaryIndex).toBeLessThan(parentTextIndex);
  expect(rToolIndex).toBeGreaterThan(parentTextIndex);
});

it("keeps a sequential sub-agent run's parts contiguous in arrival order", async () => {
  const yields = await collectYields([
    { type: "model_output_thinking", content: "parent planning " },
    {
      type: "subagent_start",
      content: JSON.stringify({
        agent_id: 31,
        agent_name: "Researcher",
        task: "collect data",
        invocation_id: "inv-r",
      }),
    },
    {
      type: "model_output_thinking",
      content: "R thinking ",
      invocation_id: "inv-r",
    },
    {
      type: "tool",
      content: "",
      tool_name: "search",
      tool_arguments: { query: "finance" },
      invocation_id: "inv-r",
    },
    {
      type: "subagent_end",
      content: JSON.stringify({ invocation_id: "inv-r" }),
    },
    { type: "model_output_thinking", content: "parent wrapping up " },
    { type: "final_answer", content: "done" },
    { type: "done", content: "" },
  ]);
  assertIndexStable(yields);

  // A run whose parts arrive contiguously still renders as one cluster: the
  // boundary stamp, reasoning and tool-call occupy consecutive indices.
  const last = yields.at(-1)!;
  const runIndices = last
    .map((part, index) => [index, part] as const)
    .filter(([, part]) => part.metadata?.runId === "run-1")
    .map(([index]) => index);
  expect(runIndices.length).toBe(3);
  expect(runIndices[1]).toBe(runIndices[0] + 1);
  expect(runIndices[2]).toBe(runIndices[0] + 2);
});

it("replaces the history-summary card in place on idle instead of splicing it out", async () => {
  const yields = await collectYields([
    { type: "model_output_thinking", content: "parent thinking " },
    {
      type: "history_summary",
      content: JSON.stringify({ status: "compacting" }),
    },
    { type: "model_output_thinking", content: "more thinking " },
    {
      type: "history_summary",
      content: JSON.stringify({
        status: "accepted",
        summary: { markdown: "earlier conversation summary" },
      }),
    },
    { type: "history_summary", content: JSON.stringify({ status: "idle" }) },
    { type: "final_answer", content: "done" },
    { type: "done", content: "" },
  ]);
  assertIndexStable(yields);

  // The idle tombstone stays at its index: present in the array (so later
  // parts keep their indices) but carrying no summary, which
  // HistorySummaryCard renders as nothing.
  const last = yields.at(-1)!;
  const tombstone = last.find(
    (part) => part.type === "data" && part.name === "history-summary"
  );
  expect(tombstone).toBeDefined();
  expect(tombstone.data.status).toBe("idle");
  expect(tombstone.data.summary).toBeUndefined();
});
