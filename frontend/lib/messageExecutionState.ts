// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { ThreadAssistantMessage } from "@assistant-ui/react";

export function messageExecutionStatus(
  outcome?: string
): ThreadAssistantMessage["status"] {
  if (outcome === "failed") return { type: "incomplete", reason: "error" };
  if (outcome === "stopped") return { type: "incomplete", reason: "cancelled" };
  if (outcome === "pending" || outcome === "streaming")
    return { type: "running" };
  return { type: "complete", reason: "stop" };
}
