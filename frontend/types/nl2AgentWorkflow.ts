// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
export interface Nl2AgentWorkflowView {
  current: number;
  status: "idle" | "running" | "waiting" | "paused" | "error" | "completed";
  detail: string;
  mode?: "hybrid" | "fuzzy";
  fallback: boolean;
  pipeline: Array<"pending" | "running" | "done" | "skipped">;
  skipped: number[];
  counts?: { completed: number; total: number };
}
