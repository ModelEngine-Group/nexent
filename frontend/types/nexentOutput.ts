// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

/** Transport facts accepted at the shared Nexent output boundary. */
export interface NexentOutputEvent {
  type: string;
  content: string;
  invocation_id?: string;
  step_id?: string;
  unit_index?: number;
  tool_call_id?: string;
  tool_name?: string;
  tool_arguments?: string | Record<string, unknown>;
  role?: string;
  answer_phase?: "delta" | "complete";
  reclassify_step?: boolean;
  [key: string]: unknown;
}

export type NexentRunStatus = "completed" | "failed" | "stopped";

export type NexentOutputStatus =
  | { type: "running" }
  | { type: "complete"; reason: "stop" }
  | { type: "incomplete"; reason: "cancelled" | "error"; error?: string };
