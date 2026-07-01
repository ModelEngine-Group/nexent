export type EvaluationSet = {
  evaluation_set_id: number;
  tenant_id: string;
  name: string;
  description?: string | null;
  source_filename?: string | null;
  case_count?: number | null;
  create_time?: string;
  update_time?: string;
};

export type EvaluationSetCase = {
  evaluation_set_case_id: number;
  evaluation_set_id: number;
  tenant_id: string;
  case_id?: string | null;
  inputs: {
    query: string;
    context?: string;
  };
  label: {
    answer: string;
  };
  order_no?: number;
};

export type AgentEvaluationRun = {
  agent_evaluation_id: number;
  tenant_id: string;
  agent_id: number;
  agent_version_no: number;
  evaluation_set_id: number;
  evaluation_set_name?: string;
  judge_model_id?: number;
  judge_model_name?: string;
  status: "PENDING" | "RUNNING" | "COMPLETED" | "FAILED";
  progress_total?: number;
  progress_done?: number;
  score_overall?: number | null;
  case_count?: number | null;
  pass_count?: number | null;
  fail_count?: number | null;
  error_message?: string | null;
  create_time?: string;
};

export type EvaluationHistoryItem = {
  agent_evaluation_id: number;
  agent_version_no: number;
  evaluation_set_name?: string;
  judge_model_name?: string;
  status: AgentEvaluationRun["status"];
  score_overall?: number | null;
  case_count?: number | null;
  pass_count?: number | null;
  fail_count?: number | null;
  progress_total?: number;
  progress_done?: number;
  create_time?: string;
};

export type AgentEvaluationCase = {
  agent_evaluation_case_id: number;
  agent_evaluation_id: number;
  evaluation_set_case_id: number;
  tenant_id: string;
  inputs: {
    query: string;
    context?: string;
  };
  label: {
    answer: string;
  };
  predict?: {
    answer?: string;
    raw?: any;
  } | null;
  score?: number | null;
  reason?: string | null;
  pass_status?: "PASS" | "FAIL" | null;
  status: "PENDING" | "RUNNING" | "COMPLETED" | "FAILED";
  error_message?: string | null;
};
