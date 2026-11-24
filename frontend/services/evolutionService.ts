// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { API_BASE_URL, API_ENDPOINTS, fetchWithErrorHandling } from "./api";
import { getAuthHeaders } from "@/lib/auth";
import type { ReviewBatch } from "@/types/evolutionReview";

const root = `${API_BASE_URL}/agent-evolution`;

export interface SuggestionReceipt {
  conversation_id: number;
  message_id: number;
}

export interface SuggestionComparison {
  agent_id: number;
  version_no: number;
  suggestion_id: number;
  experiment_id: number | null;
  candidate_id: number | null;
}

export function parseSuggestionReceipt(content: unknown): SuggestionReceipt | null {
  if (typeof content !== "string") return null;
  try {
    const result = JSON.parse(content) as SuggestionReceipt | null;
    if (result && [result.conversation_id, result.message_id].every((id) => Number.isSafeInteger(id) && id > 0)) {
      return { conversation_id: result.conversation_id, message_id: result.message_id };
    }
  } catch {
    // Invalid receipt units have no actions.
  }
  return null;
}

function receiptEndpoint(receipt: SuggestionReceipt) {
  return `${root}/conversations/${receipt.conversation_id}/receipts/${receipt.message_id}`;
}

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
  model_budget_available?: boolean;
  released_guides?: {name: string; candidate_id: number; digest: string}[];
  fixed_regression?: { source_case_id: number; source_version: number; digest: string; family: string; query: string;
    rubric?: { name: string; version_no: number } }[];
  skills?: { skill_id: number; name: string }[];
  suggestions?: {
    suggestion_id: number;
    expected_behavior: string;
    skill_id: number | null;
    released_guide_candidate_id?: number | null;
    experiment_id: number | null;
  }[];
  reviews?: { turn_id: number; batch_id: number | null; state: string; signals: string[];
    diagnosis?: { status: "needs_review" | "needs_evidence" | "no_issue"; reason: string; missing?: string[] } }[];
  review_batches?: ReviewBatch[];
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
  preceding_turns?: number;
  segments?: {task_turn_id: number; trajectory_id: string; query: string | null; attachment_count: number | null}[];
}
export interface Trial {
  status: string;
  result?: {
    evaluator_id?: number;
    evaluator_version?: number;
    trace_baseline_outcome?: string;
    turns?: { turn: number; query: string; answer: string | null; outcome: string; attachments: string[] }[];
    answer?: string;
    file_state?: {status: string; missing: string[]; extra: string[]; wrong_content: string[]; protected_writes: string[]};
    reported_step_input_tokens?: number | null;
    skill?: { guide_reads: number; listed: boolean; mounted_revision: string | null };
    skills?: { candidate_id: number; guide_reads: number; listed: boolean; mounted_revision: string | null }[];
    selection?: { expected: string[]; reads: Record<string, number>; outcome: string };
    guide_reads?: Record<string, number>;
    tool_catalog?: { core: string; prompt_tools: string[]; schema_tools: string[]; executable: string[];
      model_inputs?: number; instruction_mentions?: string[]; native_definitions?: string[] };
    new_skill_trial?: {candidate_id: number; name: string; digest: string; arm: "base" | "result"};
    tool_use?: { status: string; reason?: string; mcp_evidence?: {
      call: number; tool: string; input_matches: boolean; reply_matches: boolean; state_matches: boolean | null;
    }[]; script_evidence?: {
      call: number; exit_code: number; input_matches: boolean; stdout_matches: boolean | null; files_match?: boolean | null; script: string; image: string;
    }[]; argument_evidence?: {
      tool: string; field: string; call: number; requested: string | null; effective: string | null; expected: string;
    }[]; checked?: string[]; sequence?: string[]; issues?: { reason: string; tool?: string; fields?: string[]; max_calls?: number }[] };
    error?: string;
    judgment?: { score?: number; reason?: string; status?: string };
    previous_attempt?: { status: string; receipt_id?: string | null;
      result?: { error?: string; judgment?: { reason?: string }; tool_use?: { reason?: string } } | null };
  };
}
export interface ScreeningCriteria {
  metric: "tasks_fixed" | "skill_choices_fixed" | "input_token_reduction_pct";
  minimum: number;
  target_case_ids: number[];
}

interface DevelopmentRunBudget {
  max_replay_turns: number;
  max_elapsed_seconds: number;
  max_model_tokens?: number;
  max_model_micros?: number;
}

export interface ExperimentReport {
  can_retry?: boolean;
  budget?: DevelopmentRunBudget & { planned_replay_turns: number; deadline: string; expired_trials: number };
  model_budget?: {
    max_model_tokens: number;
    max_model_micros: number;
    calls: number;
    reported_calls: number;
    reported_input_tokens: number;
    reported_output_tokens: number;
    reported_micros: number;
    unsettled_tokens: number;
    unsettled_micros: number;
    stopped_reason: string | null;
  };
  script_source_cases?: number[];
  screening?: { status: "eligible" | "failed" | "incomplete"; criteria: ScreeningCriteria; gain: number | null;
    failures: Record<string, number[]>; missing: Record<string, number[]> };
  components?: EvaluatedCandidate[];
  valid_quartets?: number;
  fixed_regression?: { case_ids: number[]; failed: number[]; incomplete: number[] };
  experiment_id: number;
  agent_id?: number;
  version_no?: number;
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

export interface PublicBenchmarkInput {
  dataset: string;
  revision: string;
  subset: string;
  scoring_protocol: string;
  adaptation?: string;
  run_reference?: string;
  metric: string;
  sample_count: number;
  baseline_score: number;
  candidate_score: number;
}

export interface PublicBenchmarkReport extends PublicBenchmarkInput {
  report_id: number;
  experiment_id: number;
  base_snapshot_digest: string;
  candidate_snapshot_digest: string;
  created_by: string;
  create_time: string;
}

export interface NewSkillBrief {
  name: string;
  creator_id: string;
  purpose: string;
  skip_when: string;
  parameters: string[];
  successes: {case_id: number; private_values: string[]; outcomes: { step: string; excerpt: string }[]}[];
  counterexample_id: number;
  covered: {step: string; skill: string; passage: string}[];
}

export interface ApprovedExample {
  case_id: number;
  variant: "base" | "result";
  behavior: string;
  attachment_name?: string;
  input_excerpt: string;
  output_excerpt: string;
}

export interface FileStateCheck {
  adapter: "text-files-v1"; initial: Record<string, string>; expected: Record<string, string>; protected: string[];
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
  suggestionActions: (receipt: SuggestionReceipt) =>
    read<{ compare?: SuggestionComparison; edit?: { candidate_id: number } }>(`${receiptEndpoint(receipt)}/actions`),
  suggestionCandidate: (receipt: SuggestionReceipt, candidate: number) =>
    read<{ skill_name: string; old: string; new: string }>(`${receiptEndpoint(receipt)}/skill-candidates/${candidate}`),
  reviseSuggestionCandidate: (receipt: SuggestionReceipt, candidate: number, replacement: string) =>
    read<{ candidate_id: number }>(`${receiptEndpoint(receipt)}/skill-candidates/${candidate}`, { replacement }),
  async publicBenchmarks(id: number, before: number | null) {
    const endpoint = API_ENDPOINTS.evolutionPublicBenchmarks(id);
    const response = await fetchWithErrorHandling(
      before === null ? endpoint : `${endpoint}?before=${before}`,
      { headers: getAuthHeaders() },
    );
    const payload: { data: { items: PublicBenchmarkReport[]; next_before: number | null } } =
      await response.json();
    return payload.data;
  },
  async recordPublicBenchmark(id: number, values: PublicBenchmarkInput) {
    const response = await fetchWithErrorHandling(API_ENDPOINTS.evolutionPublicBenchmarks(id), {
      method: "POST",
      headers: getAuthHeaders(),
      body: JSON.stringify(values),
    });
    const payload: { data: PublicBenchmarkReport } = await response.json();
    return payload.data;
  },
  release: (id: number) => read<{
    agent_id: number; experiment_id: number; base_version: number; current_version: number;
    candidate_digest: string; candidate_type: string; supported_type: boolean; paused: boolean; excluded_tools?: string[];
    script_build?: {name: string; path: string; function: string; image: string} | null;
    tool_build?: {tool: string; base: {image: string}; result: {image: string}} | null;
    tool_mapping?: {tool: string; field: string; proposed: Record<string, {kind: string; values?: string[]}>} | null;
    components?: {experiment_id: number; candidate_type: string; candidate_id: number}[] | null;
    skill_description?: {name: string; previous: string; proposed: string} | null;
    added_guide?: {candidate_id: number; name: string; digest: string} | null;
    summary: null | {decision: "passed" | "insufficient" | "failed"; valid_pairs: number; total_pairs: number; regressed: number};
    release: null | {new_version: number; rollback_at: string | null; disabled: boolean};
  }>(`${root}/confirmation-locks/${id}/release`),
  releaseMonitoring: (id: number) => read<{
    since: string; until: string;
    versions: {version_no: number; sessions: number; executions: number; unverified: number; binding_mismatches: number; failed: number; stopped: number;
      timed: number; p90_ms: number | null; metered: number; mean_tokens: number | null; reviewed: number;
      corrected: number; tool_errors: number; missing_files: number; disliked: number}[];
    events: {action: string; actor: string; reason: string; created_at: string}[];
  }>(`${root}/confirmation-locks/${id}/release/monitoring`),
  promote: (id: number, expected_version: number, candidate_digest: string, reason: string) =>
    read(`${root}/confirmation-locks/${id}/promote`, {expected_version,candidate_digest,reason}),
  rollback: (id: number, expected_version: number, reason: string, emergency: boolean) =>
    read(`${root}/confirmation-locks/${id}/rollback`, {expected_version,reason,emergency}),
  agents: () => read<AgentChoice[]>(API_ENDPOINTS.agent.publishedList),
  versions: (agent: number) =>
    read<VersionChoice[]>(API_ENDPOINTS.agent.versions.list(agent)),
  evaluators: () => read<Rule[]>(API_ENDPOINTS.evaluators.list),
  workspace: (agent: number, version: number) =>
    read<Workspace>(`${root}/agents/${agent}/versions/${version}/workspace`),
  traceCaseDraft: (agent: number, version: number, turn: number, previous = false, preceding = 0) =>
    read<TraceCaseDraft>(`${root}/agents/${agent}/versions/${version}/reviews/${turn}/case-draft?use_previous_task=${previous}&preceding_turns=${preceding}`),
  createCase: (body: {
    agent_id: number;
    version_no: number;
    family: string;
    source_group?: string;
    query: string;
    expected: string;
    expected_skill_names?: string[];
    tool_use?: ToolExpectation;
    file_state?: FileStateCheck;
    attachments: { name: string; object_name: string }[];
    followups?: { query: string; attachment_names?: string[] }[];
    trace?: { turn_id: number; draft_digest: string; purpose: "reproduce" | "protect";
      inputs_reviewed: true; tools_require_no_reset: boolean; unused_attachment_slots?: number[]; use_previous_task?: boolean;
      preceding_turns?: number };
  }) => read<{ case_id: number }>(`${root}/development-cases`, body),
  submit: (body: {
    budget?: DevelopmentRunBudget;
    components?: EvaluatedCandidate[];
    suggestion_id?: number;
    suggestion_target_case_id?: number;
    request_id: string;
    screening?: ScreeningCriteria;
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
  confirmationResults: (id: number) => read<Array<{
    lock_id: number;
    summary: null | { decision: "passed" | "failed" | "insufficient"; valid_pairs: number;
      total_pairs: number; regressed: number; quality_gain_pp: number | null; missing?: string[];
      model_usage?: { input_tokens: number; output_tokens: number; cost_micros: number;
        unsettled_tokens: number; unsettled_micros: number } };
  }>>(`${root}/experiments/${id}/confirmation-results`),
  nominate: (id: number) => read<{ experiment_id: number; candidate_digest: string }>(
    `${root}/experiments/${id}/confirmation-candidate`, {}),
  setFixedRegression: (agent: number, version: number, id: number, enabled: boolean,
    scoring?: { evaluator_id: number; judge_model_id?: number; language: string }) =>
    read<{ case_id: number; enabled: boolean }>(
      `${root}/agents/${agent}/versions/${version}/development-cases/${id}/regression`, { enabled, ...scoring }),
  toolMappingCandidate: (id: number, body: {
    failure_case_id: number; protection_case_id: number; tool_name: string; field: string; supplied_value: string;
  }) => read<{candidate_id: number; tool: string; field: string; rule: {kind: string; values?: string[]}}>(
    `${root}/experiments/${id}/tool-mapping-candidates`, body),
  toolSetCandidates: (id: number, failure_case_ids: number[], protection_case_ids: number[]) =>
    read<{ variants: { candidate_id: number | null; removed: string[]; retained: string[] }[] }>(
      `${root}/experiments/${id}/tool-set-candidates`, { failure_case_ids, protection_case_ids }),
  developmentCase: (agent: number, version: number, id: number) =>
    read<{ task: { query: string; expected: string; tool_use?: ToolExpectation } }>(
      `${root}/agents/${agent}/versions/${version}/development-cases/${id}`),
  shareLocalEdit: (id: number, body: LocalFeedback) =>
    read<{ feedback_id: number }>(`${root}/experiments/${id}/feedback`, body),
  shareToolRepair: (id: number, body: ToolRepairFeedback) =>
    read<{feedback_id: number}>(`${root}/experiments/${id}/tool-repair-feedback`, body),
  registerToolBuild: (feedback: number, body: {base_image: string; result_image: string; review: string; port: number; path: string; transport: string}) =>
    read<{build_id: number}>(`${root}/feedback/${feedback}/tool-builds`, body),
  toolBuildIds: (feedback: number) => read<number[]>(`${root}/feedback/${feedback}/tool-builds`),
  toolBuildStatus: (id: number) => read<{caller_count: number; missing_caller_count: number; case_count: number;
    manifest: {base_image: string; result_image: string; review: string};
    verification: null | {status: string; cases: {label: string; outcome: string}[]}}>(`${root}/tool-builds/${id}`),
  approveToolCaller: (build: number, body: {experiment_id: number; case_id: number; tool_name: string; share_example: true}) =>
    read<{case_id: number}>(`${root}/tool-builds/${build}/caller-cases`,body),
  toolRepairBrief: (id: number) =>
    read<{test_suite: {format: "nexent-mcp-repair-v1"; failure: ToolExpectation["rules"][number]; protection: ToolExpectation["rules"][number]};
      tool_name: string; goal: string; failure: {arguments: Record<string, unknown>; expected: ExpectedMcpReply};
      protection: {arguments: Record<string, unknown>; expected: ExpectedMcpReply}; repeat_receipt: string}>(
      `${root}/feedback/${id}/tool-repair-brief`),
  shareScriptFeedback: (id: number, body: ScriptFeedback) =>
    read<{feedback_id: number}>(`${root}/experiments/${id}/skill-script-feedback`, body),
  scriptDraft: (id: number, body: {model_id: number} | {replacement: string}) =>
    read<{script_path: string; function: string; replacement: string; diff: string; draft_digest: string; source_digest: string}>(
      `${root}/feedback/${id}/skill-script-draft`, body),
  buildScript: (id: number, body: {replacement: string; draft_digest: string; source_digest: string}) =>
    read<{candidate_id: number; method: string; package_digest: string; image: string}>(
      `${root}/feedback/${id}/skill-script-build`, body),
  shareDiscovery: (id: number, body: { method: "S1"; skill_id: number; goal: string } &
    Record<"missed" | "overused" | "correct", { case_id: number; query_excerpt: string }>) =>
    read<{ feedback_id: number }>(`${root}/experiments/${id}/feedback`, body),
  newSkillBrief: (id: number, body: NewSkillBrief) =>
    read<{feedback_id: number; steps: string[]; covered: string[]}>(`${root}/experiments/${id}/new-skill-brief`, body),
  fromFeedback: (id: number, model_id: number) =>
    read<{ candidate_id: number; method: string; edit?: { old: string; new: string }; files?: Record<string, string> }>(
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
  retry: (id: number) =>
    read<ExperimentReport>(`${root}/experiments/${id}/retry`, {}),
};

export type ExpectedMcpReply = {
  kind: "text" | "structured"; value: string | Record<string, unknown>; error?: boolean;
  fixture?: {initial: Record<string, unknown>; final: Record<string, unknown>};
};

export interface ToolExpectation {
  rules: { name: string; min_calls: number; max_calls: number | null; expected_mcp_reply?: ExpectedMcpReply; expected_script_stdout?: string; expected_script_files?: Record<string, string>; arguments: Record<string, unknown> }[];
  order?: string[];
}

export interface ToolRepairFeedback {
  tool_name: string; failure_case_id: number; protection_case_id: number; repeat_experiment_id: number;
  goal: string; share_tool_examples: true;
}
export interface ScriptFeedback {
  skill_id: number; failure_case_id: number; protection_case_id: number; repeat_experiment_id: number;
  function: string; goal: string; share_script_examples: boolean;
}

export interface LocalFeedback {
  method: "P1" | "P3" | "T1" | "T2" | "S2";
  goal: string;
  source_passage: string;
  related_passage?: string;
  tool_name?: string;
  skill_id?: number;
  released_guide_candidate_id?: number;
  suggestion_id?: number;
  share_expected_arguments?: string[];
  share_file_state?: boolean;
  failure: { case_id: number; expected: string; observed: string; input_excerpt?: string };
  protection: { case_id: number; expected: string; observed: string; input_excerpt?: string };
}
