// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import type {
  MonitoringCoverage,
  MonitoringDateScope,
  MonitoringPublication,
} from "./operations";

export interface AgentMonitoringSelection extends MonitoringDateScope {
  agentId: number | null;
  groupIds: number[];
}

export type AgentPublication = MonitoringPublication;
export type AgentCoverage = MonitoringCoverage;

export interface AgentTokenUsage {
  value: string | null;
  known_count: number;
  eligible_count: number;
  coverage_rate: number | null;
}

interface AgentTokenMetrics {
  total_tokens: AgentTokenUsage | null;
}

export interface AgentExecutionMetrics {
  execution_count: number | null;
  succeeded_count: number | null;
  failed_count: number | null;
  success_rate: number | null;
}

interface AgentMonitoringResponse extends AgentPublication {
  token_status: AgentPublication;
}

export interface AgentMonitoringSummary extends AgentMonitoringResponse {
  data: AgentExecutionMetrics;
  tokens: AgentTokenMetrics;
}

export interface AgentMonitoringDay extends AgentExecutionMetrics {
  statistic_date: string;
  coverage_state: AgentCoverage;
  tokens: AgentTokenMetrics;
  token_status: AgentPublication;
}

export interface AgentMonitoringTrends extends AgentMonitoringResponse {
  data: AgentMonitoringDay[];
}

export type AgentMonitoringMetric =
  "execution_count" | "total_tokens" | "success_rate";

export type AgentListSort =
  AgentMonitoringMetric | "avg_duration_ms" | "avg_ttft_ms";

export interface AgentListRequest {
  page: number;
  pageSize: number;
  search: string;
  sortBy: AgentListSort;
  descending: boolean;
}

export interface AgentMonitoringRow {
  tenant_id: string;
  agent_id: number;
  name?: string | null;
  display_name?: string | null;
  model_ids?: number[] | null;
  is_current: boolean;
  metrics:
    | (AgentExecutionMetrics & {
        avg_duration_ms: number | null;
        avg_ttft_ms: number | null;
      })
    | null;
  tokens: AgentTokenMetrics;
  token_status: AgentPublication;
}

export interface AgentMonitoringList extends AgentMonitoringResponse {
  data: {
    items: AgentMonitoringRow[];
    total: number;
    current_agent_count: number;
  };
}

export interface AgentRankingRow extends Omit<
  AgentMonitoringRow,
  "metrics" | "tokens" | "token_status"
> {
  metrics: (AgentExecutionMetrics & { success_sample_count?: number }) | null;
  tokens?: AgentTokenMetrics;
  token_status?: AgentPublication;
}

export interface AgentMonitoringRankings extends AgentPublication {
  data: AgentRankingRow[];
  token_status?: AgentPublication;
}
