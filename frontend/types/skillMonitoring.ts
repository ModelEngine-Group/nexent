// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import type { MonitoringDateScope, MonitoringPublication } from "./operations";

export interface SkillMonitoringSelection extends MonitoringDateScope {
  skillId: string | null;
  groupIds: number[];
}

export interface SkillMonitoringSummary extends MonitoringPublication {
  data: {
    current_skill_count: number;
    usage_count: number;
    skill_count: number;
  };
}

export interface SkillMonitoringTrend extends MonitoringPublication {
  data: { statistic_date: string; usage_count: number | null }[];
}

export interface SkillMonitoringRow {
  tenant_id: string | null;
  skill_id: string;
  skill_name: string | null;
  source?: string | null;
  metrics: { usage_count: number } | null;
}

export interface SkillMonitoringPage extends MonitoringPublication {
  data: { items: SkillMonitoringRow[]; total: number };
}

export interface SkillMonitoringRankings extends MonitoringPublication {
  data: SkillMonitoringRow[];
}

export type SkillMonitoringQueryKey = readonly [
  "skillMonitoring",
  string,
  string,
  SkillMonitoringSelection | null,
];
