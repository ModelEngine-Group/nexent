import type { Agent, AgentCore } from "@/types/agentConfig";
import { DEFAULT_AGENT_VERIFICATION_CONFIG } from "@/types/agentConfig";

/** Apply native Jiuwen limitations without changing supported resources. */
export function compatibleCorePatch<T extends Partial<Agent>>(
  current: Partial<Agent> | null,
  patch: T
): T & Partial<Agent> {
  const core: AgentCore =
    patch.agent_core ?? current?.agent_core ?? "smolagents";
  if (core !== "jiuwen") return patch;
  const verification =
    patch.verification_config ?? current?.verification_config;
  return {
    ...patch,
    enable_context_manager: false,
    provide_run_summary: false,
    enable_protocol_repair_retry: false,
    verification_config: {
      ...DEFAULT_AGENT_VERIFICATION_CONFIG,
      ...verification,
      enabled: false,
      guardrail_config: {
        ...DEFAULT_AGENT_VERIFICATION_CONFIG.guardrail_config!,
        ...verification?.guardrail_config,
        enabled: false,
      },
    },
    sub_agent_id_list: [],
    sub_agent_relations: [],
    external_sub_agent_id_list: [],
  };
}
