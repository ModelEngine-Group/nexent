// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { parseNl2AgentState } from "../adapter/remote-chat-model-adapter";
import type { Nl2AgentWorkflowView } from "@/types/nl2AgentWorkflow";

const record = (value: unknown): Record<string, unknown> =>
  value !== null && typeof value === "object"
    ? (value as Record<string, unknown>)
    : {};

export function hasCompletedCreation(
  messages: readonly unknown[],
  agentId: number | null
): boolean {
  return messages.some((value) => {
    const message = record(value);
    if (message.role !== "assistant") return false;
    const events = record(record(message.metadata).custom).nl2agentStates;
    return (
      Array.isArray(events) &&
      events.some((raw) => {
        const event = parseNl2AgentState(JSON.stringify(raw));
        return (
          event?.agent_id === agentId &&
          event.event === "agent_generation_completed"
        );
      })
    );
  });
}

/** Restore workflow visibility from scoped resource facts or explicit tool intent. */
export function isFullGenerationTurn(
  messages: readonly unknown[],
  agentId: number | null
): boolean {
  let creating = false;
  let resourceWorkflow = false;
  let partialIntent = false;
  let completed = false;
  for (const value of messages) {
    const message = record(value);
    if (message.role === "user" && completed) {
      creating = false;
      resourceWorkflow = false;
      partialIntent = false;
      completed = false;
    }
    if (message.role !== "assistant") continue;
    // History may retain cards/receipts without the original tool invocation.
    // Prompt-only edits are also used for optimization and do not prove creation.
    const custom = record(record(message.metadata).custom);
    const card = record(record(custom.nl2a).content);
    resourceWorkflow ||=
      (card.agent_id === agentId &&
        [
          "requirement_clarification",
          "requirement_coverage",
          "resource_recommendation",
          "installed_resource_binding",
          "suggested_resource_installation",
        ].includes(String(card.subtype))) ||
      (Array.isArray(custom.nl2agentStates) &&
        custom.nl2agentStates.some((raw) => {
          const event = parseNl2AgentState(JSON.stringify(raw));
          return (
            event?.agent_id === agentId &&
            [
              "resource_retrieval_progress",
              "agent_generation_completed",
            ].includes(event.event)
          );
        }));
    for (const value of Array.isArray(message.content) ? message.content : []) {
      const part = record(value);
      if (part.type !== "tool-call") continue;
      let args = record(part.args);
      if (typeof part.argsText === "string") {
        try {
          args = record(JSON.parse(part.argsText));
        } catch {
          /* Incomplete arguments are not intent. */
        }
      }
      if (args.agent_id !== undefined && args.agent_id !== agentId) continue;
      partialIntent ||=
        part.toolName === "nl2a_discover_requirements" &&
        ["recommend", "bind"].includes(String(args.purpose));
      creating ||=
        part.toolName === "nl2a_validate_agent_generation_complete" ||
        (part.toolName === "nl2a_read_generation_context" &&
          args.goal === "complete") ||
        (part.toolName === "nl2a_discover_requirements" &&
          args.purpose === "generate");
    }
    completed ||= hasCompletedCreation([message], agentId);
  }
  return creating || (resourceWorkflow && !partialIntent);
}

/** Presentation only: no model prose, user intent or tool start proves completion. */
export function projectNl2AgentWorkflow({
  agentId,
  messages,
  isRunning,
  phase,
}: {
  agentId: number | null;
  messages: readonly unknown[];
  isRunning: boolean;
  phase: string;
}): Nl2AgentWorkflowView {
  const view: Nl2AgentWorkflowView = {
    current: 0,
    status: "idle",
    detail: "ready",
    fallback: false,
    pipeline: ["pending", "pending", "pending"],
    skipped: [],
  };
  let run = "";
  let sequence = 0;
  let coverageSeen = false;
  let bindingSeen = false;
  let lastCard = -1;
  let lastUser = -1;
  let lastFact = -1;
  const retiredRuns = new Set<string>();
  for (const [index, unknownMessage] of messages.entries()) {
    const message = record(unknownMessage);
    if (message.role === "user") {
      lastUser = index;
      continue;
    }
    if (message.role !== "assistant") continue;
    const custom = record(record(message.metadata).custom);
    for (const raw of Array.isArray(custom.nl2agentStates)
      ? custom.nl2agentStates
      : []) {
      const event = parseNl2AgentState(JSON.stringify(raw));
      if (!event || event.agent_id !== agentId) continue;
      lastFact = index;
      if (event.event === "resource_retrieval_progress") {
        if (run === event.run_id && sequence >= event.sequence) continue;
        if (run !== event.run_id) {
          if (retiredRuns.has(event.run_id)) continue;
          if (run) retiredRuns.add(run);
          run = event.run_id;
          sequence = 0;
          view.mode = undefined;
          view.fallback = false;
          view.pipeline = ["pending", "pending", "pending"];
        }
        sequence = event.sequence;
        view.current = 1;
        coverageSeen = true;
        view.status = "running";
        view.detail = event.stage;
        if (
          event.stage === "searching_hybrid" ||
          event.stage === "preparing_embeddings" ||
          event.stage === "computing_similarity"
        )
          view.mode = "hybrid";
        if (event.stage === "searching_text") {
          view.mode = "fuzzy";
          view.pipeline[0] = "skipped";
          view.pipeline[1] = "running";
        }
        if (
          event.stage === "searching_hybrid" ||
          event.stage === "preparing_embeddings"
        )
          view.pipeline[0] = "running";
        if (event.stage === "computing_similarity")
          view.pipeline = ["done", "running", "pending"];
        if (event.stage === "fallback_to_text") {
          view.fallback = true;
          view.mode = "fuzzy";
          view.pipeline = ["skipped", "running", "pending"];
        }
        if (event.stage === "verifying_capabilities")
          view.pipeline = [
            view.mode === "hybrid" ? "done" : "skipped",
            "done",
            "running",
          ];
        view.counts =
          event.completed !== undefined && event.total !== undefined
            ? { completed: event.completed, total: event.total }
            : undefined;
      } else if (event.event === "agent_draft_fields_saved") {
        if (
          event.updated_fields.some((field) =>
            ["prompt", "greeting_message", "example_questions"].includes(field)
          )
        ) {
          view.current = 3;
          view.status = "running";
          view.detail = event.updated_fields.includes("example_questions")
            ? "validating"
            : event.updated_fields.includes("greeting_message")
              ? "examples"
              : "conversation";
        }
      } else if (event.event === "prompt_generation_failed") {
        view.current = 3;
        view.status = "error";
        view.detail = "failed";
      } else if (event.event === "agent_generation_completed") {
        view.current = 3;
        view.status = "completed";
        view.detail = "completed";
      }
    }
    const card = record(record(custom.nl2a).content);
    if (card.agent_id === agentId && typeof card.subtype === "string") {
      const subtype = card.subtype;
      if (subtype === "prompt_generation") {
        lastCard = index;
        lastFact = index;
        view.current = 3;
        if (card.status === "pending") {
          view.status = "waiting";
          view.detail = "confirmPrompt";
        } else if (card.status === "cancelled") {
          view.status = "paused";
          view.detail = "promptCancelled";
        }
      }
      if (
        [
          "requirement_clarification",
          "requirement_coverage",
          "resource_recommendation",
          "installed_resource_binding",
          "suggested_resource_installation",
        ].includes(subtype)
      ) {
        lastCard = index;
        lastFact = index;
        view.status = "waiting";
        if (subtype === "requirement_clarification") {
          view.current = 0;
          view.detail = "confirmRequirements";
        } else if (subtype === "installed_resource_binding") {
          bindingSeen = true;
          coverageSeen = true;
          view.current = 2;
          view.detail = "selectResources";
        } else {
          coverageSeen = true;
          view.current = 1;
          view.detail =
            subtype === "resource_recommendation"
              ? "recommendationReady"
              : "resolveGaps";
        }
        if (view.current >= 1)
          view.pipeline = [
            view.mode === "hybrid" ? "done" : "skipped",
            "done",
            "done",
          ];
      }
    }
    for (const item of Array.isArray(message.content) ? message.content : []) {
      const part = record(item);
      if (
        part.type === "data" &&
        part.name === "nl2agent-created" &&
        record(part.data).agentId === agentId &&
        record(part.data).completed === true
      ) {
        view.current = 3;
        view.status = "completed";
        view.detail = "completed";
      }
      if (part.isError === true) {
        view.status = "error";
        view.detail = "failed";
      }
      if (
        isRunning &&
        index === messages.length - 1 &&
        part.type === "tool-call" &&
        part.isError !== true &&
        view.status !== "error" &&
        typeof part.toolName === "string"
      ) {
        let args = record(part.args);
        if (typeof part.argsText === "string" && part.argsText.trim()) {
          try {
            args = record(JSON.parse(part.argsText));
          } catch {
            continue;
          }
        }
        if (args.agent_id !== undefined && args.agent_id !== agentId) continue;
        // Context reading starts prompt composition; its result can arrive long
        // before the first prompt save. This indicates activity, not completion.
        const startsGeneration =
          view.current < 3 &&
          (part.toolName === "nl2a_read_generation_context" ||
            (part.toolName === "nl2a_save_agent_draft_fields" &&
              typeof record(args.fields).prompt === "string"));
        if (
          startsGeneration ||
          (!part.result &&
            [
              "nl2a_save_agent_draft_fields",
              "nl2a_validate_agent_generation_complete",
            ].includes(part.toolName) &&
            (view.current === 3 || part.toolName.includes("validate")))
        ) {
          view.current = 3;
          view.status = "running";
          view.detail = "generating";
        }
      }
    }
  }
  if (phase === "generation_failed") {
    view.current = 3;
    view.status = "error";
    view.detail = "failed";
  }
  if (phase === "completed") {
    view.current = 3;
    view.status = "completed";
    view.detail = "completed";
  }
  if (phase === "completing") {
    view.current = 3;
    view.detail = "synchronizing";
  }
  if (lastUser > lastFact && ["completed", "error"].includes(view.status)) {
    view.status = isRunning ? "running" : "paused";
    view.detail = isRunning ? "processing" : "paused";
  }
  if (isRunning && view.status !== "completed" && view.status !== "error") {
    view.status = "running";
    if (
      lastUser > lastCard &&
      [
        "resolveGaps",
        "confirmRequirements",
        "selectResources",
        "recommendationReady",
      ].includes(view.detail)
    )
      view.detail = "processing";
  } else if (!isRunning && view.status === "running") {
    view.status = "paused";
    view.detail = "paused";
  }
  if (view.current === 3)
    view.skipped = [
      ...(!coverageSeen ? [1] : []),
      ...(!bindingSeen ? [2] : []),
    ];
  return view;
}
