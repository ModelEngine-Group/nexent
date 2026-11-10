// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type {
  NexentOutputEvent as Event,
  NexentOutputStatus,
  NexentRunStatus,
} from "@/types/nexentOutput";

interface Run {
  source: Event;
  sequence: number;
  blocks: Map<string, string>;
  calls: Map<string, string>;
  results: Set<string>;
  result?: Event;
  invalid?: string;
  emitted?: boolean;
  step: string;
}

function object(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function envelope(event: Event): Event {
  try {
    const nested: unknown = JSON.parse(event.content);
    if (
      object(nested) &&
      nested.schema_version === 1 &&
      nested.runtime_mode === "native_agent" &&
      nested.type === event.type &&
      typeof nested.content === "string" &&
      typeof nested.turn_id === "string"
    )
      return {
        ...event,
        ...nested,
        unit_index: event.unit_index ?? nested.unit_index,
      } as Event;
  } catch {
    /* Ordinary text is already a Nexent event. */
  }
  return event;
}

function native(event: Event) {
  return (
    event.schema_version === 1 &&
    event.runtime_mode === "native_agent" &&
    typeof event.turn_id === "string"
  );
}

export function outputStatus(
  status?: string,
  error?: string
): NexentOutputStatus | undefined {
  if (!status) return undefined;
  if (status === "running" || status === "streaming")
    return { type: "running" };
  if (status === "completed") return { type: "complete", reason: "stop" };
  return {
    type: "incomplete",
    reason: status === "stopped" ? "cancelled" : "error",
    ...(error && { error }),
  };
}

/** Normalize public run facts into existing Nexent events, never UI parts or Core-specific views. */
export function createNexentOutputAdapter() {
  const runs = new Map<string, Run>();
  const byInvocation = new Map<string, Run>();
  const duplicates = new Set<string>();
  let root: Run | undefined;
  let closed = false;
  const duplicateKey = (e: Event) =>
    JSON.stringify([e.invocation_id ?? "", e.type, e.content]);
  const converted = (
    e: Event,
    type: string,
    fields: Partial<Event> = {}
  ): Event => ({ ...e, type, ...fields });
  const failure = (run: Run, reason: string) => {
    run.invalid = reason;
  };
  const resultStatus = (run: Run): NexentRunStatus =>
    run.invalid
      ? "failed"
      : ((run.result?.status as NexentRunStatus) ?? "failed");
  const complete = (run: Run): Event[] => {
    if (run.emitted) return [];
    run.emitted = true;
    const result = run.result;
    const status = resultStatus(run);
    const source = result ?? run.source;
    if (status === "completed") {
      const ids = result?.final_block_ids as string[];
      return [
        converted(source, "final_answer", {
          content: String(result?.final_content ?? ""),
          answer_phase: "complete",
          reclassify_step: true,
          step_id: run.blocks.get(ids?.[0]) ?? source.step_id ?? run.step,
        }),
      ];
    }
    if (status === "stopped") return [];
    const error = object(result?.error) ? result.error : {};
    return [
      converted(source, "error", {
        content:
          run.invalid ??
          String(
            error.safe_message ??
              result?.end_reason ??
              "NEXENT_TERMINAL_MISSING"
          ),
      }),
    ];
  };
  const push = (raw: Event): Event[] => {
    const e = raw;
    if (!native(e)) {
      const run = byInvocation.get(e.invocation_id ?? "");
      if (
        run &&
        (e.type === "tool" || e.type === "tool-call") &&
        e.tool_call_id
      ) {
        const key = JSON.stringify([
          run.source.turn_id,
          e.invocation_id ?? "",
          e.tool_call_id,
        ]);
        run.calls.set(e.tool_call_id, key);
        return [converted(e, e.type, { tool_call_id: key })];
      }
      if (
        run &&
        (e.type === "final_answer" ||
          (e.type === "token_count" && !e.content.includes('"step_number"')))
      )
        return [];
      if (e.type === "execution_logs" && duplicates.has(duplicateKey(e)))
        return [];
      if (e.type === "subagent_end") {
        let payload: Record<string, unknown> = {};
        try {
          payload = JSON.parse(e.content);
        } catch {
          /* Keep older boundaries unchanged. */
        }
        const child = byInvocation.get(
          String(payload.invocation_id ?? e.invocation_id ?? "")
        );
        if (child)
          return [
            ...complete(child),
            converted(e, e.type, {
              content: JSON.stringify({
                ...payload,
                status: resultStatus(child),
              }),
            }),
          ];
      }
      if (run && e.tool_call_id && run.calls.has(e.tool_call_id))
        return [
          converted(e, e.type, { tool_call_id: run.calls.get(e.tool_call_id) }),
        ];
      return [e];
    }
    const id = String(e.turn_id);
    let run = runs.get(id);
    if (!run) {
      run = {
        source: e,
        sequence: 0,
        blocks: new Map(),
        calls: new Map(),
        results: new Set(),
        step: e.step_id ?? id,
      };
      runs.set(id, run);
      byInvocation.set(e.invocation_id ?? "", run);
      if (!e.invocation_id) root = run;
    }
    if (closed || run.result || run.emitted) {
      failure(run, "NEXENT_OUTPUT_AFTER_TERMINAL");
      return [];
    }
    if (
      typeof e.sequence !== "number" ||
      !Number.isInteger(e.sequence) ||
      e.sequence <= run.sequence
    ) {
      failure(run, "NEXENT_OUTPUT_ORDER_INVALID");
      return [];
    }
    run.sequence = e.sequence;
    if (e.type === "step_count") {
      run.step = e.step_id ?? `${id}:step:${e.content}`;
      return [converted(e, e.type, { step_id: run.step })];
    }
    if (e.type === "model_output" || e.type === "model_output_deep_thinking") {
      const block = String(e.block_id ?? e.step_id ?? run.step);
      const first = !run.blocks.has(block);
      const step = run.blocks.get(block) ?? e.step_id ?? block;
      run.blocks.set(block, step);
      const boundary =
        first && run.step !== step
          ? [converted(e, "step_count", { content: "", step_id: step })]
          : [];
      run.step = step;
      return [
        ...boundary,
        converted(
          e,
          e.type === "model_output" ? "model_output_thinking" : e.type,
          { step_id: step, origin_type: e.type }
        ),
      ];
    }
    if (e.type === "tool") {
      const local = String(e.local_call_id ?? e.tool_call_id ?? "");
      if (!local || run.calls.has(local)) {
        failure(run, "NEXENT_TOOL_ID_INVALID");
        return [];
      }
      const key = JSON.stringify([id, e.invocation_id ?? "", local]);
      run.calls.set(local, key);
      return [converted(e, "tool", { tool_call_id: key })];
    }
    if (e.type === "tool_result") {
      const key = run.calls.get(
        String(e.local_call_id ?? e.tool_call_id ?? "")
      );
      if (!key || run.results.has(key)) {
        failure(run, "NEXENT_TOOL_RESULT_UNPAIRED");
        return [];
      }
      run.results.add(key);
      const output = converted(e, "execution_logs", {
        content: String(e.result ?? e.content),
        tool_call_id: key,
      });
      duplicates.add(duplicateKey(output));
      return [output];
    }
    if (e.type === "step_observation") {
      const usage = object(e.usage) ? e.usage : {};
      const capacity = object(e.context_capacity) ? e.context_capacity : {};
      const warning = object(e.step_error)
        ? [
            converted(e, "warning", {
              content: String(
                e.step_error.safe_message ??
                  e.step_error.category ??
                  "Model step failed"
              ),
            }),
          ]
        : [];
      return [
        ...warning,
        converted(e, "token_count", {
          content: JSON.stringify({
            step_number: e.step_number,
            duration: e.duration,
            step_input_tokens: usage.input_tokens ?? null,
            step_output_tokens: usage.output_tokens ?? null,
            total_output_tokens: usage.output_tokens ?? null,
            context_window_tokens: capacity.context_window_tokens ?? null,
            token_threshold: capacity.token_threshold ?? null,
            effective_input_limit_tokens: capacity.effective_input_limit_tokens ?? null,
            context_processing_mode: capacity.context_processing_mode ?? null,
          }),
        }),
      ];
    }
    if (e.type === "run_terminal") {
      if (
        !["completed", "failed", "stopped"].includes(String(e.status)) ||
        (e.status !== "completed" &&
          (e.final_content ||
            (Array.isArray(e.final_block_ids) && e.final_block_ids.length))) ||
        (e.status === "completed" &&
          (e.error ||
            typeof e.final_content !== "string" ||
            !Array.isArray(e.final_block_ids)))
      )
        failure(run, "NEXENT_TERMINAL_INVALID");
      run.result = e;
      return [];
    }
    return [e];
  };
  return {
    push,
    close(persistedStatus?: string) {
      if (closed) return [];
      closed = true;
      for (const run of runs.values()) {
        if (!run.result) failure(run, "NEXENT_TERMINAL_MISSING");
        if (
          run === root &&
          persistedStatus === "failed" &&
          resultStatus(run) !== "failed"
        )
          failure(run, "NEXENT_PERSISTED_RUN_FAILED");
        if (run === root && persistedStatus === "stopped") {
          run.invalid = undefined;
          run.result = {
            ...run.source,
            status: "stopped",
            type: "run_terminal",
            content: "",
          };
        }
      }
      return [...runs.values()].flatMap(complete);
    },
    get status() {
      return root
        ? outputStatus(
            closed ? resultStatus(root) : "running",
            root.invalid ??
              (object(root.result?.error)
                ? String(root.result.error.safe_message ?? "")
                : undefined)
          )
        : undefined;
    },
  };
}

/** Decode both persisted envelopes and original units without consulting the Agent's current Core. */
export function normalizeNexentHistory(events: Event[], status?: string) {
  const adapter = createNexentOutputAdapter();
  const normalized = [
    ...events.map(envelope).flatMap(adapter.push),
    ...adapter.close(status),
  ];
  const providers = new Map(
    normalized
      .filter((e) => e.type === "execution_logs" && e.provider_call_id)
      .map((e) => [e.tool_call_id, e.provider_call_id])
  );
  for (const event of normalized)
    if (event.type === "tool" && !event.provider_call_id)
      event.provider_call_id = providers.get(event.tool_call_id);
  const finals = new Set(
    normalized
      .filter((e) => e.type === "final_answer" && e.reclassify_step)
      .map((e) => JSON.stringify([e.invocation_id ?? "", e.step_id]))
  );
  return {
    events: normalized.filter(
      (e) =>
        !(
          e.origin_type === "model_output" &&
          finals.has(JSON.stringify([e.invocation_id ?? "", e.step_id]))
        )
    ),
    status: adapter.status ?? outputStatus(status),
  };
}

/** Wrap only the transport; all normalized bytes enter the original SSE parser. */
export function adaptNexentOutputStream(
  source: ReadableStreamDefaultReader<Uint8Array>
) {
  const adapter = createNexentOutputAdapter();
  const decoder = new TextDecoder(),
    encoder = new TextEncoder();
  let buffer = "",
    finished = false;
  const convert = (line: string) => {
    if (!line.startsWith("data:")) return line + "\n";
    try {
      const raw: unknown = JSON.parse(line.slice(5).trim());
      if (
        !object(raw) ||
        typeof raw.type !== "string" ||
        typeof raw.content !== "string"
      )
        return line + "\n";
      return adapter
        .push(raw as Event)
        .map((e) => `data: ${JSON.stringify(e)}\n\n`)
        .join("");
    } catch {
      return line + "\n";
    }
  };
  const stream = new ReadableStream<Uint8Array>({
    async pull(controller) {
      try {
        while (!finished) {
          const { value, done } = await source.read();
          if (finished) return;
          buffer += decoder.decode(value, { stream: !done });
          const lines = buffer.split(/\r?\n/);
          buffer = lines.pop() ?? "";
          let output = lines.map(convert).join("");
          if (done) {
            finished = true;
            if (buffer) output += convert(buffer);
            output += adapter
              .close()
              .map((e) => `data: ${JSON.stringify(e)}\n\n`)
              .join("");
            source.releaseLock();
          }
          if (output) controller.enqueue(encoder.encode(output));
          if (finished) controller.close();
          if (output || finished) return;
        }
      } catch (error) {
        finished = true;
        adapter.close("failed");
        source.releaseLock();
        controller.error(error);
      }
    },
    async cancel(reason) {
      finished = true;
      adapter.close("stopped");
      try {
        await source.cancel(reason);
      } finally {
        source.releaseLock();
      }
    },
  });
  return { reader: stream.getReader(), adapter };
}
