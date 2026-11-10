// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { describe, expect, it } from "vitest";
import { ReadableStream } from "node:stream/web";
import {
  createNexentOutputAdapter,
  normalizeNexentHistory,
  adaptNexentOutputStream,
} from "@/lib/nexentOutputAdapter";
import type { NexentOutputEvent as Event } from "@/types/nexentOutput";

const event = (
  type: string,
  sequence: number,
  extra: Partial<Event> = {}
): Event => ({
  type,
  content: "",
  schema_version: 1,
  runtime_mode: "native_agent",
  agent_core: "jiuwen",
  turn_id: "root",
  sequence,
  ...extra,
});
const terminal = (sequence: number, extra: Partial<Event> = {}) =>
  event("run_terminal", sequence, {
    status: "completed",
    final_content: "Final",
    final_block_ids: ["final"],
    ...extra,
  });
const body = () =>
  event("model_output", 1, { block_id: "final", content: "Final" });
const saved = (events: Event[]) =>
  events.map((e, unit_index) => ({
    type: e.type,
    content: JSON.stringify(e),
    unit_index,
  }));

async function bytes(events: Event[], size = 3, newline = true) {
  const raw = events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join("");
  const input = new TextEncoder().encode(newline ? raw : raw.trimEnd());
  const source = new ReadableStream<Uint8Array>({
    start(c) {
      for (let i = 0; i < input.length; i += size)
        c.enqueue(input.slice(i, i + size));
      c.close();
    },
  });
  const { reader, adapter } = adaptNexentOutputStream(
    source.getReader() as ReadableStreamDefaultReader<Uint8Array>
  );
  let text = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    text += new TextDecoder().decode(value);
  }
  return {
    events: text
      .split("\n")
      .filter((l) => l.startsWith("data:"))
      .map((l) => JSON.parse(l.slice(5))),
    status: adapter.status,
  };
}

describe("Nexent output boundary, shared by all Core renderers", () => {
  it("maps process, reasoning, tools and exact results to original event types", () => {
    const adapter = createNexentOutputAdapter();
    const out = [
      event("model_output", 1, { block_id: "one", content: "Before" }),
      event("model_output_deep_thinking", 2, {
        block_id: "one",
        content: "Explicit reasoning",
      }),
      event("tool", 3, {
        local_call_id: "local",
        provider_call_id: "provider-" + "x".repeat(300),
        tool_name: "mcp",
        tool_arguments: { a: 1 },
      }),
      event("tool_result", 4, {
        local_call_id: "local",
        result: "Exact result",
        is_error: true,
      }),
    ].flatMap(adapter.push);
    expect(out.map((e) => e.type)).toEqual([
      "step_count",
      "model_output_thinking",
      "model_output_deep_thinking",
      "tool",
      "execution_logs",
    ]);
    expect(out[3].provider_call_id).toHaveLength(309);
    expect(out[4].tool_call_id).toBe(out[3].tool_call_id);
    expect(out[4].content).toBe("Exact result");
    expect(out[4].is_error).toBe(true);
  });

  it("waits for explicit complete result and emits one original final event", () => {
    const adapter = createNexentOutputAdapter();
    adapter.push(body());
    expect(adapter.push({ type: "final_answer", content: "Final" })).toEqual(
      []
    );
    expect(adapter.push(terminal(2))).toEqual([]);
    const out = adapter.close();
    expect(out).toHaveLength(1);
    expect(out[0]).toMatchObject({
      type: "final_answer",
      content: "Final",
      answer_phase: "complete",
      reclassify_step: true,
      step_id: "final",
    });
    expect(adapter.status).toEqual({ type: "complete", reason: "stop" });
    expect(adapter.close()).toEqual([]);
  });

  it.each(["failed", "stopped"])(
    "keeps partial without a false final for %s",
    (status) => {
      const input = [
        body(),
        terminal(2, {
          status,
          final_content: "",
          final_block_ids: [],
          end_reason: "fault",
        }),
      ];
      const history = normalizeNexentHistory(saved(input), status);
      expect(history.events.some((e) => e.type === "final_answer")).toBe(false);
      expect(
        history.events.find((e) => e.type === "model_output_thinking")?.content
      ).toBe("Final");
      expect(history.status?.type).toBe("incomplete");
    }
  );

  it.each(["missing", "repeat", "order", "after"])(
    "fails closed for %s terminal control",
    (fault) => {
      const adapter = createNexentOutputAdapter();
      adapter.push(body());
      if (fault !== "missing")
        adapter.push(terminal(fault === "order" ? 1 : 2));
      if (fault === "repeat") adapter.push(terminal(3));
      if (fault === "after")
        adapter.push(
          event("model_output", 3, { block_id: "late", content: "Late" })
        );
      expect(adapter.close().every((e) => e.type !== "final_answer")).toBe(
        true
      );
      expect(adapter.status).toMatchObject({ reason: "error" });
    }
  );

  it("keeps simultaneous child calls with identical local IDs isolated", () => {
    const adapter = createNexentOutputAdapter();
    const a = adapter.push(
      event("tool", 1, {
        turn_id: "a",
        invocation_id: "a",
        local_call_id: "same",
      })
    )[0];
    const b = adapter.push(
      event("tool", 1, {
        turn_id: "b",
        invocation_id: "b",
        local_call_id: "same",
      })
    )[0];
    const result = adapter.push(
      event("tool_result", 2, {
        turn_id: "b",
        invocation_id: "b",
        local_call_id: "same",
        result: "B",
      })
    )[0];
    expect(a.tool_call_id).not.toBe(b.tool_call_id);
    expect(result.tool_call_id).toBe(b.tool_call_id);
    expect(adapter.status).toBeUndefined();
  });

  it("rejects an unpaired result without attaching it to another call", () => {
    const adapter = createNexentOutputAdapter();
    expect(
      adapter.push(
        event("tool_result", 1, { local_call_id: "missing", result: "Wrong" })
      )
    ).toEqual([]);
    adapter.push(terminal(2));
    expect(adapter.close()[0].type).toBe("error");
  });

  it("preserves unknown usage as null and retains explicit zero", () => {
    const adapter = createNexentOutputAdapter();
    const e = adapter.push(
      event("step_observation", 1, {
        usage: { input_tokens: null, output_tokens: 0 },
        step_number: 1,
      })
    )[0];
    expect(JSON.parse(e.content)).toMatchObject({
      step_input_tokens: null,
      step_output_tokens: 0,
    });
  });

  it("passes all legacy messages through without checking Core names", () => {
    const adapter = createNexentOutputAdapter();
    const legacy = { type: "final_answer", content: "Legacy" };
    expect(adapter.push(legacy)).toEqual([legacy]);
    expect(adapter.status).toBeUndefined();
    const future = normalizeNexentHistory(
      [body(), terminal(2)].map((e) => ({ ...e, agent_core: "future-core" })),
      "completed"
    );
    expect(future.events.find((e) => e.type === "final_answer")?.content).toBe(
      "Final"
    );
    expect(future.events.some((e) => e.origin_type === "model_output")).toBe(
      false
    );
  });

  it("preserves legacy parent and child final answers in mixed-Core runs", () => {
    const adapter = createNexentOutputAdapter();
    expect(
      adapter.push({ type: "final_answer", content: "Parent" })
    ).toHaveLength(1);
    adapter.push(
      event("model_output", 1, {
        turn_id: "child",
        invocation_id: "child",
        block_id: "child",
        content: "Child",
      })
    );
    expect(
      adapter.push({
        type: "final_answer",
        invocation_id: "child",
        content: "Child",
      })
    ).toEqual([]);
    adapter.push(
      terminal(2, {
        turn_id: "child",
        invocation_id: "child",
        final_content: "Child",
        final_block_ids: ["child"],
      })
    );
    const out = adapter.push({
      type: "subagent_end",
      content: '{"invocation_id":"child"}',
    });
    expect(out.map((e) => e.type)).toEqual(["final_answer", "subagent_end"]);
    expect(JSON.parse(out[1].content).status).toBe("completed");
    expect(adapter.close()).toEqual([]);
    expect(adapter.status).toBeUndefined();
  });

  it("does not swallow a legacy child's final under a native parent", () => {
    const adapter = createNexentOutputAdapter();
    adapter.push(body());
    expect(
      adapter.push({
        type: "final_answer",
        invocation_id: "legacy-child",
        content: "Child",
      })
    ).toHaveLength(1);
  });

  it("keeps failure classification when reloading failed persisted state", () => {
    const out = normalizeNexentHistory(
      saved([
        terminal(1, {
          status: "failed",
          final_content: "",
          final_block_ids: [],
          error: { safe_message: "MODEL_TRANSPORT_ERROR" },
        }),
      ]),
      "failed"
    );
    expect(out.events[0].content).toBe("MODEL_TRANSPORT_ERROR");
    expect(out.status).toMatchObject({ error: "MODEL_TRANSPORT_ERROR" });
  });

  it.each([true, false])(
    "handles UTF-8 fragmentation and final newline=%s",
    async (newline) => {
      const input = [body(), terminal(2, { final_content: "图片粉色" })];
      const out = await bytes(input, 1, newline);
      expect(out.events.filter((e) => e.type === "final_answer")).toHaveLength(
        1
      );
      expect(out.events.at(-1).content).toBe("图片粉色");
      expect(out.status?.type).toBe("complete");
    }
  );

  it("does not expose any UI-part or renderer-specific envelope", () => {
    const out = normalizeNexentHistory(saved([body(), terminal(2)]));
    expect(
      out.events.every((e) => e.type !== "data" && e.name !== "runtime-output")
    ).toBe(true);
    expect(out.events.filter((e) => e.type === "final_answer")).toHaveLength(1);
  });
});

it("does not interpret live model JSON as another protocol envelope", () => {
  const adapter = createNexentOutputAdapter();
  const content = JSON.stringify(terminal(99));
  const out = adapter.push(
    event("model_output", 1, { block_id: "json", content })
  );
  expect(out.at(-1)?.content).toBe(content);
  expect(adapter.close().at(-1)?.type).toBe("error");
});

it("restores the backend's already-unwrapped tool unit with its exact result ID", () => {
  const units = [
    ...saved([body()]),
    {
      type: "tool",
      content: "",
      tool_name: "image",
      tool_call_id: "id",
      tool_arguments: {},
    },
    ...saved([
      event("tool_result", 2, { local_call_id: "id", result: "Pink" }),
      terminal(3),
    ]),
  ];
  const out = normalizeNexentHistory(units, "completed");
  const tool = out.events.find((e) => e.type === "tool"),
    result = out.events.find((e) => e.type === "execution_logs");
  expect(tool?.tool_call_id).toBe(result?.tool_call_id);
  expect(result?.content).toBe("Pink");
  expect(out.status?.type).toBe("complete");
});

it("propagates cancellation to the source and retains an incomplete status", async () => {
  let cancelled = false;
  const source = new ReadableStream<Uint8Array>({
    start(c) {
      c.enqueue(
        new TextEncoder().encode(`data: ${JSON.stringify(body())}\n\n`)
      );
    },
    cancel() {
      cancelled = true;
    },
  });
  const output = adaptNexentOutputStream(
    source.getReader() as ReadableStreamDefaultReader<Uint8Array>
  );
  await output.reader.read();
  await output.reader.cancel();
  expect(cancelled).toBe(true);
  expect(output.adapter.status).toMatchObject({
    type: "incomplete",
    reason: "cancelled",
  });
});

it("does not promote a terminal after a visible transport failure", async () => {
  let reads = 0;
  const source = new ReadableStream<Uint8Array>({
    pull(c) {
      if (reads++ === 0)
        c.enqueue(
          new TextEncoder().encode(`data: ${JSON.stringify(body())}\n\n`)
        );
      else c.error(new Error("transport closed"));
    },
  });
  const output = adaptNexentOutputStream(
    source.getReader() as ReadableStreamDefaultReader<Uint8Array>
  );
  await output.reader.read();
  await expect(output.reader.read()).rejects.toThrow("transport closed");
  expect(output.adapter.status).toMatchObject({
    type: "incomplete",
    reason: "error",
  });
});
