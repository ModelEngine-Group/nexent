// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import type { SkillMonitoringSummary } from "@/types/skillMonitoring";

export function getSkillUsageCount(
  summary: SkillMonitoringSummary
): number | null {
  if (
    summary.coverage_state === "uncovered" ||
    (summary.coverage_state === "partial" && summary.data.skill_count === 0)
  ) {
    return null;
  }
  return summary.data.usage_count;
}
