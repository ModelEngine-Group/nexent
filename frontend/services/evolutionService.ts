// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { API_BASE_URL, API_ENDPOINTS } from "./api";
import { getAuthHeaders } from "@/lib/auth";

const root = `${API_BASE_URL}/agent-evolution`;

interface AgentChoice {
  agent_id: number;
  name: string;
  display_name?: string;
}
interface VersionChoice {
  version_no: number;
  version_name?: string;
}
interface Rule {
  evaluator_id: number;
  name: string;
  evaluator_type: string;
  status: string;
}
export interface Workspace {
  fixed_regression?: { source_case_id: number; source_version: number; digest: string; family: string; query: string;
    rubric?: { name: string; version_no: number } }[];
  skills?: { skill_id: number; name: string }[];
  suggestions?: { suggestion_id: number; expected_behavior: string; skill_id: number; experiment_id: number | null }[];
  reviews?: { turn_id: number; batch_id: number | null; state: string; signals: string[] }[];
  candidates: { candidate_id: number; kind: string; name: string }[];
  cases: { case_id: number; digest?: string; family: string; query: string; expected_skill_names?: string[] | null }[];
  experiments: { experiment_id: number; create_time: string; candidate_type?: string;
    candidate_id?: number; eligible_component?: boolean }[];
}
export interface EvaluatedCandidate { experiment_id: number; candidate_type: string; candidate_id: number }
export interface TraceCaseDraft {
  turn_id: number; trajectory_id: string; draft_digest: string; query: string | null;
  attachment_count: number | null; attachment_names?: string[]; tool_count: number; tools: { node: string; invocation_id?: string }[];
  signals: string[];
  correction_query?: string | null; correction_trajectory_id?: string | null;
}
export interface Trial {
  status: string;
  result?: {
    evaluator_id?: number;
    evaluator_version?: number;
    trace_baseline_outcome?: string;
    answer?: string;
    reported_step_input_tokens?: number | null;
    skill?: { guide_reads: number; listed: boolean; mounted_revision: string | null };
    skills?: { candidate_id: number; guide_reads: number; listed: boolean; mounted_revision: string | null }[];
    selection?: { expected: string[]; reads: Record<string, number>; outcome: string };
    guide_reads?: Record<string, number>;
    tool_catalog?: { core: string; prompt_tools: string[]; schema_tools: string[]; executable: string[];
      model_inputs?: number; instruction_mentions?: string[]; native_definitions?: string[] };
    tool_use?: { status: string; checked?: string[]; sequence?: string[]; issues?: { reason: string; tool?: string; fields?: string[]; max_calls?: number }[] };
    error?: string;
    judgment?: { score?: number; reason?: string; status?: string };
  };
}
export interface ExperimentReport {
  components?: EvaluatedCandidate[];
  valid_quartets?: number;
  fixed_regression?: { case_ids: number[]; failed: number[]; incomplete: number[] };
  experiment_id: number;
  status: string;
  valid_pairs: number;
  total_pairs: number;
  valid_baselines?: number;
  total_tasks?: number;
  valid_triplets?: number;
  verified_guide_pairs?: number;
  pairs: Record<string, { base: Trial; result?: Trial; no_skill?: Trial; only_a?: Trial; only_b?: Trial; comparison: string;
    combination?: { effect: string; a_vs_base: string; b_vs_base: string; combined_vs_a: string; combined_vs_b: string };
    skill_vs_absent?: { base: string; result: string } }>;
}

export interface ApprovedExample {
  case_id: number;
  variant: "base" | "result";
  behavior: string;
  attachment_name?: string;
  input_excerpt: string;
  output_excerpt: string;
}

async function read<T>(url: string, body?: unknown): Promise<T> {
  const response = await fetch(url, {
    method: body === undefined ? "GET" : "POST",
    headers: getAuthHeaders(),
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const payload = await response.json();
  if (
    !response.ok ||
    (typeof payload.code === "number" && payload.code !== 0)
  ) {
    const message = [payload.detail, payload.message].find(
      (value) => typeof value === "string"
    );
    throw new Error(message || `HTTP ${response.status}`);
  }
  return payload.data ?? payload.items ?? payload;
}

export const evolutionService = {
  agents: () => read<AgentChoice[]>(API_ENDPOINTS.agent.publishedList),
  versions: (agent: number) =>
    read<VersionChoice[]>(API_ENDPOINTS.agent.versions.list(agent)),
  evaluators: () => read<Rule[]>(API_ENDPOINTS.evaluators.list),
  workspace: (agent: number, version: number) =>
    read<Workspace>(`${root}/agents/${agent}/versions/${version}/workspace`),
  traceCaseDraft: (agent: number, version: number, turn: number, previous = false) =>
    read<TraceCaseDraft>(`${root}/agents/${agent}/versions/${version}/reviews/${turn}/case-draft${previous ? "?use_previous_task=true" : ""}`),
  createCase: (body: {
    agent_id: number;
    version_no: number;
    family: string;
    source_group?: string;
    query: string;
    expected: string;
    expected_skill_names?: string[];
    tool_use?: ToolExpectation;
    attachments: { name: string; object_name: string }[];
    trace?: { turn_id: number; draft_digest: string; purpose: "reproduce" | "protect";
      inputs_reviewed: true; tools_require_no_reset: boolean; unused_attachment_slots?: number[]; use_previous_task?: boolean };
  }) => read<{ case_id: number }>(`${root}/development-cases`, body),
  submit: (body: {
    components?: EvaluatedCandidate[];
    suggestion_id?: number;
    suggestion_target_case_id?: number;
    request_id: string;
    agent_id: number;
    version_no: number;
    candidate_type: string;
    candidate_id?: number;
    case_ids: number[];
    evaluator_id: number;
    judge_model_id?: number;
    language: string;
  }) => read<{ experiment_id: number }>(`${root}/experiments`, body),
  report: (id: number) => read<ExperimentReport>(`${root}/experiments/${id}`),
  setFixedRegression: (agent: number, version: number, id: number, enabled: boolean,
    scoring?: { evaluator_id: number; judge_model_id?: number; language: string }) =>
    read<{ case_id: number; enabled: boolean }>(
      `${root}/agents/${agent}/versions/${version}/development-cases/${id}/regression`, { enabled, ...scoring }),
  toolSetCandidates: (id: number, failure_case_ids: number[], protection_case_ids: number[]) =>
    read<{ variants: { candidate_id: number | null; removed: string[]; retained: string[] }[] }>(
      `${root}/experiments/${id}/tool-set-candidates`, { failure_case_ids, protection_case_ids }),
  developmentCase: (agent: number, version: number, id: number) =>
    read<{ task: { query: string; expected: string; tool_use?: ToolExpectation } }>(
      `${root}/agents/${agent}/versions/${version}/development-cases/${id}`),
  shareLocalEdit: (id: number, body: LocalFeedback) =>
    read<{ feedback_id: number }>(`${root}/experiments/${id}/feedback`, body),
  shareDiscovery: (id: number, body: { method: "S1"; skill_id: number; goal: string } &
    Record<"missed" | "overused" | "correct", { case_id: number; query_excerpt: string }>) =>
    read<{ feedback_id: number }>(`${root}/experiments/${id}/feedback`, body),
  fromFeedback: (id: number, model_id: number) =>
    read<{ candidate_id: number; method: string; edit: { old: string; new: string } }>(
      `${root}/feedback/${id}/candidates`, { model_id }),
  exampleCandidates: (id: number, body: {
    target_case_id: number;
    target_behavior: string;
    examples: ApprovedExample[];
  }) => read<{ variants: { candidate_id: number | null; example_count: number }[] }>(
    `${root}/experiments/${id}/example-candidates`, body
  ),
  cancel: (id: number) =>
    read<ExperimentReport>(`${root}/experiments/${id}/cancel`, {}),
};

export interface ToolExpectation {
  rules: { name: string; min_calls: number; max_calls: number | null; arguments: Record<string, unknown> }[];
  order?: string[];
}

export interface LocalFeedback {
  method: "P1" | "P3" | "T1" | "T2" | "S2";
  goal: string;
  source_passage: string;
  tool_name?: string;
  skill_id?: number;
  share_expected_arguments?: string[];
  failure: { case_id: number; expected: string; observed: string; input_excerpt?: string };
  protection: { case_id: number; expected: string; observed: string; input_excerpt?: string };
}
