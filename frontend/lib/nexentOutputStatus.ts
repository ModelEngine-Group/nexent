// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { NexentOutputStatus } from "@/types/nexentOutput";

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
