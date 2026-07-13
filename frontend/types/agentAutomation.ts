export type ScheduleMode = "ONCE" | "RECURRING";
export type ScheduleRuleType = "AT" | "INTERVAL" | "CRON";
export type AutomationTaskStatus =
  | "DRAFT"
  | "ACTIVE"
  | "PAUSED"
  | "PAUSED_BY_SYSTEM"
  | "COMPLETED"
  | "DELETED";

export interface ScheduleTrigger {
  mode: ScheduleMode;
  rule_type: ScheduleRuleType;
  timezone: string;
  start_at: string;
  end_at?: string | null;
  cron_expr?: string | null;
  interval_seconds?: number | null;
  max_fire_count?: number | null;
}

export interface CapabilityBinding {
  type: string;
  name: string;
  display_name?: string;
  binding_ref: string;
  reason?: string;
  required?: boolean;
}

export interface AgentAutomationTask {
  task_id: number;
  tenant_id: string;
  user_id: string;
  conversation_id: number;
  agent_id: number;
  agent_version_no?: number | null;
  title: string;
  instruction: string;
  status: AutomationTaskStatus;
  source: string;
  schedule_mode: ScheduleMode;
  schedule_rule_type: ScheduleRuleType;
  schedule_expr?: string | null;
  schedule_config: ScheduleTrigger;
  capability_requirements?: Record<string, unknown>;
  capability_bindings?: CapabilityBinding[];
  runtime_snapshot?: Record<string, unknown>;
  timezone: string;
  next_fire_at?: string | null;
  last_fire_at?: string | null;
  fire_count: number;
  last_run_status?: string | null;
  last_error?: string | null;
  consecutive_failures: number;
  timeout_seconds?: number;
}

export interface AgentAutomationRun {
  run_id: number;
  task_id: number;
  conversation_id: number;
  scheduled_fire_at: string;
  actual_fire_at?: string | null;
  trigger_type: string;
  status: string;
  generated_prompt?: string | null;
  error_code?: string | null;
  error_message?: string | null;
}

export interface AgentAutomationProposalData {
  proposal_id?: number | null;
  conversation_id?: number | null;
  confidence?: number;
  intent_analysis_source?: "llm" | "rule";
  task_content_source?: "llm" | "rule";
  executable?: boolean;
  task?: {
    title?: string;
    instruction?: string;
    agent_id?: number;
    agent_version_no?: number | null;
    model_id?: number | null;
    tool_params?: Record<string, unknown> | null;
    schedule_trigger?: ScheduleTrigger;
  } | null;
  capability_resolution?: {
    executable?: boolean;
    matched_capabilities?: CapabilityBinding[];
    missing_capabilities?: CapabilityBinding[];
    agent_snapshot?: Record<string, unknown>;
  } | null;
  confirmed_task_id?: number;
}

export interface UpdateAutomationTaskPayload {
  title?: string;
  instruction?: string;
  agent_version_no?: number | null;
  model_id?: number | null;
  tool_params?: Record<string, unknown> | null;
  schedule_trigger: ScheduleTrigger;
  capability_bindings?: CapabilityBinding[];
  timeout_seconds?: number;
}
