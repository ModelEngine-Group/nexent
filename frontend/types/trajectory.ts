// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

export interface TrajectoryFilters {
  tenant_id?: string;
  target_user_id?: string;
  agent_id?: string;
  conversation_id?: string;
  id_query?: string;
  model?: string;
  status?: "success" | "error" | "not_captured" | "expired";
  started_from?: string;
  started_to?: string;
}
export type DirectoryField =
  "tenant_id" | "target_user_id" | "agent_id" | "conversation_id";
export type TrajectoryFacet =
  "tenants" | "users" | "agents" | "conversations" | "models";
export interface DirectoryOption {
  id: string;
  name: string | null;
  tenant_id: string;
  tenant_name?: string;
}
export interface FacetPage {
  items: DirectoryOption[];
  next_cursor: string | null;
}
export interface Coverage {
  complete: boolean | null;
  reasons?: string[];
  scope?: string;
  missing_parent?: boolean;
  capture_gap?: boolean;
}
export interface Usage {
  input: number | null;
  output: number | null;
  total: number | null;
  complete: boolean;
  known?: { input: number; output: number; total: number };
}
export interface TrajectoryRecord {
  round_count?: number;
  execution_count?: number;
  matching_execution_count?: number;
  cleanup_reason?: string | null;
  tenant_id: string;
  tenant_name: string;
  user_id: string;
  user_name: string;
  conversation_id: string;
  conversation_title: string | null;
  trajectory_id: string | null;
  root_agent_id: string | null;
  root_agent_name: string | null;
  root_agent_version_no: number | null;
  root_agent_version_name: string | null;
  models: string[];
  status: "success" | "error" | null;
  business_status: string | null;
  availability: string;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  usage: Usage | null;
  coverage: Coverage;
}
export interface Percentiles {
  p50_ms: number | null;
  p90_ms: number | null;
  p99_ms: number | null;
  sample_count: number;
}
export interface TrajectorySummary {
  scope_type?: "tenant" | "global";
  scope_id?: string;
  computed_at?: string | null;
  source_revision?: number;
  computed_revision?: number;
  execution_count?: number | null;
  conversation_count: number | null;
  duration: Percentiles & { mean_ms: number | null };
  conversation_duration?: Percentiles;
  ttft: Percentiles;
  complete: boolean;
  coverage: Coverage;
}
export interface RecordsPage {
  query_id: string;
  as_of: string;
  items: TrajectoryRecord[];
  total: number;
  page: number;
  page_size: number;
  summary: TrajectorySummary;
}
export interface RecordsRequest extends TrajectoryFilters {
  view?: "execution" | "conversation";
  query_id?: string;
  page?: number;
  page_size?: number;
  sort_by?: "started_at" | "duration_ms" | "total_tokens";
  sort_order?: "asc" | "desc";
}
export interface ContentReference {
  availability: string;
  type?: string;
  text: string | null;
  preview?: string;
  complete: boolean;
  content_id: string | null;
  byte_count?: number;
  char_count?: number;
}
export interface TrajectoryNode {
  trajectory_id?: string;
  round_no?: number;
  execution_root_id?: string;
  matches_filters?: boolean;
  id: string;
  parent_id: string | null;
  display_trace_id: string;
  kind: "agent" | "model" | "tool" | string;
  name: string;
  status: string;
  agent_version_no: number | null;
  agent_version_name: string | null;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  usage: Usage | null;
  ttft_ms: number | null;
  throughput: number | null;
  direct_child_count: number;
  model_call_count: number | null;
  tool_call_count: number | null;
  model: string | null;
  user: string;
  user_id: string;
  input: ContentReference;
  output: ContentReference;
  reasoning: ContentReference;
  raw?: ContentReference;
  attributes: Record<string, unknown>;
  source: { trace_id: string; span_id: string; export_seq: string };
}
export interface SnapshotPage {
  snapshot_id: string;
  conversation_id: string;
  trajectory_id: string;
  root_node_id: string | null;
  nodes: TrajectoryNode[];
  context_nodes: TrajectoryNode[];
  next_cursor: string | null;
  coverage: Coverage;
  scope: { kind: string; complete: boolean; aggregates: string };
}
export interface ContentChunk {
  text: string;
  offset: number;
  next_offset: number;
  complete: boolean;
  offset_unit: "utf8_bytes";
  byte_count: number;
  char_count: number;
}
export interface CleanupSchedule {
  tenant_id: string;
  interval_seconds: number;
  enabled: boolean;
  retention_days: number;
}

export interface CleanupResult {
  cutoff_at: string;
  scanned_runs: number;
  deleted_runs: number;
  deleted_bytes: number;
  skipped_active: number;
  pending_runs: number;
  failed_runs: number;
  next_cursor: string | null;
  done: boolean;
}

export interface TrajectoryExecution {
  trajectory_id: string;
  round_no: number;
  turn_no: number;
  root_agent_id: string | null;
  root_agent_version_no: number | null;
  root_agent_version_name: string | null;
  business_status: string;
  availability: string;
  matches_filters: boolean;
}
export interface ConversationPage {
  snapshot_id: string;
  conversation_id: string;
  executions: TrajectoryExecution[];
  next_cursor: string | null;
  coverage: Coverage;
  availability: string;
  active_execution_count: number;
}
