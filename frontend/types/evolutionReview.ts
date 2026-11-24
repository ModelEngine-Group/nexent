// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
interface PendingReviewBatch {
  batch_id: number;
  state: "pending";
}

interface CompletedReviewBatch {
  batch_id: number;
  state: "completed";
  reviewed: number;
  excluded: number;
  missing: number;
  findings: { direction: string; reason: string; turn_ids: number[] }[];
  reference_workflows: { tools: string[]; turn_ids: number[] }[];
  draft_turns: { turn_id: number; use_previous_task: boolean }[];
}

export type ReviewBatch = PendingReviewBatch | CompletedReviewBatch;
