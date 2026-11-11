// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

export type NexentOutputStatus =
  | { type: "running" }
  | { type: "complete"; reason: "stop" }
  | { type: "incomplete"; reason: "cancelled" | "error"; error?: string };
