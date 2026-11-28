// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { ThreadAssistantMessage } from "@assistant-ui/react";

type ExecutionMessagePart = {
  type: string;
  isError?: boolean;
  invocation_id?: string;
  metadata?: { subagentId?: string };
};

export function hasRootExecutionError(parts: ExecutionMessagePart[]): boolean {
  return parts.some(
    (part) =>
      part.type === "text" &&
      part.isError === true &&
      !part.invocation_id &&
      !part.metadata?.subagentId
  );
}

export function messageExecutionStatus(
  outcome?: string
): ThreadAssistantMessage["status"] {
  if (outcome === "failed") return { type: "incomplete", reason: "error" };
  if (outcome === "stopped") return { type: "incomplete", reason: "cancelled" };
  if (outcome === "pending" || outcome === "streaming")
    return { type: "running" };
  return { type: "complete", reason: "stop" };
}
