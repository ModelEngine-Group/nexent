// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import type { ModelMonitoringCounts } from "@/types/modelMonitoring";

export type ModelTrendMetric = "requests" | "tokens" | "errorRate";

export function getModelMetric(
  counts: ModelMonitoringCounts,
  metric: ModelTrendMetric
) {
  if (metric === "requests") return counts.request_count;
  if (metric === "tokens") return counts.total_tokens?.value ?? null;
  return counts.error_eligible_count ? counts.error_rate : null;
}
