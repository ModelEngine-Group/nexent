// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import type { AgentTokenUsage } from "./agentMonitoring";
import type { MonitoringDateScope, MonitoringPublication } from "./operations";

export interface ModelMonitoringTrends extends MonitoringPublication {
  data: ModelMonitoringDay[];
}

export interface ModelMonitoringCounts {
  request_count: number | null;
  total_tokens: AgentTokenUsage | null;
  error_count: number | null;
  error_eligible_count: number | null;
  error_rate: number | null;
}

export interface ModelMonitoringDay extends ModelMonitoringCounts {
  statistic_date: string;
}

export interface ModelMonitoringSummary extends MonitoringPublication {
  data: ModelMonitoringCounts & { current_model_count: number };
}

export interface ModelMonitoringSelection extends MonitoringDateScope {
  modelId: number | null;
  groupIds: number[];
}

export type ModelListSort =
  | "name"
  | "request_count"
  | "error_rate"
  | "avg_duration_ms"
  | "avg_ttft_ms"
  | "avg_generation_rate"
  | "total_tokens";

export interface ModelListRequest {
  page: number;
  pageSize: number;
  search: string;
  sortBy: ModelListSort;
  descending: boolean;
}

export interface ModelMonitoringRow {
  tenant_id: string;
  model_id: number;
  model_name?: string | null;
  display_name?: string | null;
  model_type?: string | null;
  model_factory?: string | null;
  connect_status?: string | null;
  metrics: {
    request_count: number;
    error_rate: number | null;
    avg_duration_ms: number | null;
    avg_ttft_ms: number | null;
    total_tokens: AgentTokenUsage;
    avg_generation_rate: number | null;
  } | null;
}

export interface ModelMonitoringList extends MonitoringPublication {
  data: { items: ModelMonitoringRow[]; total: number };
}
