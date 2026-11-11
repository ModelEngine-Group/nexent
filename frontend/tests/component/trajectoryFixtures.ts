// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type {
  ContentReference,
  RecordsPage,
  TrajectoryNode,
  TrajectoryRecord,
} from "@/types/trajectory";

export const body = (text = "input", complete = true): ContentReference => ({
  availability: "available",
  text,
  complete,
  content_id: "signed-content",
  byte_count: complete ? new TextEncoder().encode(text).length : 10000000,
  char_count: text.length,
});
export const traceNode = (
  overrides: Partial<TrajectoryNode> = {}
): TrajectoryNode => ({
  id: "root",
  parent_id: null,
  display_trace_id: "9223372036854775806",
  kind: "agent",
  name: "Root Agent",
  status: "completed",
  started_at: "2026-11-10T01:00:00Z",
  finished_at: "2026-11-10T01:00:02Z",
  duration_ms: 2000,
  usage: { input: 2, output: 0, total: 2, complete: true },
  ttft_ms: null,
  throughput: null,
  direct_child_count: 2,
  model_call_count: 1,
  tool_call_count: 1,
  model: null,
  user: "Owner",
  user_id: "owner",
  input: body(),
  output: body("output"),
  reasoning: { ...body(), availability: "not_returned", text: null },
  attributes: {},
  source: { trace_id: "otel", span_id: "span", export_seq: "1" },
  ...overrides,
});
export const record: TrajectoryRecord = {
  tenant_id: "tenant",
  tenant_name: "Tenant",
  user_id: "owner",
  user_name: "Owner",
  conversation_id: "9223372036854775806",
  conversation_title: "Conversation",
  trajectory_id: "execution",
  root_agent_id: "12",
  root_agent_name: "Root Agent",
  models: ["model"],
  status: "success",
  business_status: "completed",
  availability: "available",
  started_at: "2026-11-10T01:00:00Z",
  finished_at: "2026-11-10T01:00:02Z",
  duration_ms: 2000,
  usage: { input: 2, output: 0, total: 2, complete: true },
  coverage: { complete: true },
};
export const recordsPage = (query_id = "signed-query"): RecordsPage => ({
  query_id,
  as_of: "2026-11-10T01:00:00Z",
  items: [record],
  total: 42,
  page: 1,
  page_size: 10,
  summary: {
    conversation_count: 30,
    duration: {
      mean_ms: 3000,
      p50_ms: 1000,
      p90_ms: 2000,
      p99_ms: 4000,
      sample_count: 40,
    },
    ttft: { p50_ms: 0, p90_ms: 100, p99_ms: null, sample_count: 30 },
    complete: true,
    coverage: { complete: true },
  },
});
