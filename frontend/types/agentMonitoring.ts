// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
export interface AgentMonitoringSelection {
  tenantId: string | null;
  agentId: number | null;
  groupIds: number[];
  startDate: string;
  endDate: string;
}

export type AgentCoverage = "covered" | "partial" | "uncovered";

export interface AgentPublication {
  coverage_state: AgentCoverage;
  data_as_of: string | null;
  is_stale: boolean;
}

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
