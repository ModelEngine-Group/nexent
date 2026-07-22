import dayjs, { type Dayjs } from "dayjs";

import type {
  AgentAutomationProposalData,
  ScheduleRuleType,
  ScheduleTrigger,
  UpdateAutomationProposalPayload,
} from "@/types/agentAutomation";

export interface AutomationProposalFormValues {
  title: string;
  instruction: string;
  mode: "ONCE" | "RECURRING";
  rule_type: Exclude<ScheduleRuleType, "AT">;
  start_at: Dayjs;
  timezone: string;
  cron_expr?: string;
  interval_seconds?: number;
}

export function proposalToFormValues(
  proposal: AgentAutomationProposalData
): AutomationProposalFormValues {
  const trigger = proposal.task?.schedule_trigger;
  if (!trigger) {
    throw new Error("Automation proposal does not have a schedule trigger");
  }
  return {
    title: proposal.task?.title || "",
    instruction: proposal.task?.instruction || "",
    mode: trigger.mode,
    rule_type: trigger.rule_type === "INTERVAL" ? "INTERVAL" : "CRON",
    start_at: dayjs(trigger.start_at),
    timezone: trigger.timezone,
    cron_expr: trigger.cron_expr || "0 9 * * *",
    interval_seconds: trigger.interval_seconds || 3600,
  };
}

export function formValuesToProposalPatch(
  values: AutomationProposalFormValues,
  originalTrigger: ScheduleTrigger
): UpdateAutomationProposalPayload {
  const common = {
    timezone: values.timezone,
    start_at: values.start_at.toISOString(),
    end_at: originalTrigger.end_at,
  };
  let scheduleTrigger: ScheduleTrigger;
  if (values.mode === "ONCE") {
    scheduleTrigger = {
      ...common,
      mode: "ONCE",
      rule_type: "AT",
      max_fire_count: 1,
    };
  } else if (values.rule_type === "INTERVAL") {
    scheduleTrigger = {
      ...common,
      mode: "RECURRING",
      rule_type: "INTERVAL",
      interval_seconds: values.interval_seconds,
      max_fire_count: originalTrigger.max_fire_count,
    };
  } else {
    scheduleTrigger = {
      ...common,
      mode: "RECURRING",
      rule_type: "CRON",
      cron_expr: values.cron_expr,
      max_fire_count: originalTrigger.max_fire_count,
    };
  }
  return {
    title: values.title.trim(),
    instruction: values.instruction.trim(),
    schedule_trigger: scheduleTrigger,
  };
}
