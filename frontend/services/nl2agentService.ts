/**
 * NL2AGENT frontend service.
 *
 * Wraps the /nl2agent/* backend endpoints used by the conversational agent
 * builder. The chat itself runs through the existing POST /agent/run
 * endpoint; this service only handles session management (start, apply-local,
 * install-web-skill, finalize).
 */

import { fetchWithAuth } from "@/lib/auth";
import { API_ENDPOINTS } from "@/services/api";
import log from "@/lib/logger";

export interface Nl2AgentSessionStartResponse {
  nl2agent_agent_id: number;
  draft_agent_id: number;
  conversation_id: number;
  draft_name: string;
  /** Backward-compatible alias if older deployments still return it. */
  agent_id?: number;
}

export interface Nl2AgentApplyLocalResourcesPayload {
  tool_ids: number[];
  skill_ids: number[];
}

export interface Nl2AgentApplyLocalResourcesResponse {
  bound_tool_count: number;
  bound_skill_count: number;
  tool_ids: number[];
  skill_ids: number[];
}

export interface Nl2AgentInstallWebSkillResponse {
  skill_id: number;
  skill_name?: string;
  installed: boolean;
  installed_ids: number[];
  installed_names?: string[];
}

export interface Nl2AgentInstallWebSkillPayload {
  skill_id?: number;
  skill_name?: string;
}

export interface Nl2AgentFinalizePayload {
  // Identity
  name?: string;
  display_name?: string;
  description?: string;

  // LLM models
  business_logic_model_id?: number;
  model_ids?: number[];

  // Task & template
  business_description?: string;
  prompt_template_id?: number;
  duty_prompt?: string;
  constraint_prompt?: string;
  few_shots_prompt?: string;

  // UI
  greeting_message?: string;
  example_questions?: string[];

  // Runtime
  max_steps?: number;
  requested_output_tokens?: number;
  provide_run_summary?: boolean;
  verification_config?: { enabled: boolean; mode?: string };
  enable_context_manager?: boolean;

  // Resources
  tool_ids?: number[];
  skill_ids?: number[];
  sub_agent_ids?: number[];

  // Per-agent config overrides
  tool_configs?: Record<string, Record<string, unknown>>;
  skill_configs?: Record<string, Record<string, unknown>>;
}

export interface Nl2AgentFinalizeResponse {
  agent_id: number;
  status: string;
}

/**
 * Start a new NL2AGENT session. Creates a draft agent and a conversation.
 */
export const startNl2AgentSession = async (): Promise<Nl2AgentSessionStartResponse> => {
  const response = await fetchWithAuth(API_ENDPOINTS.nl2agent.sessionStart, {
    method: "POST",
  });
  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new Error(`Failed to start NL2AGENT session: ${response.status} ${text}`);
  }
  return response.json();
};

/**
 * Bulk-bind local tools and skills to the draft agent ("Apply All").
 */
export const applyLocalResources = async (
  agentId: number,
  payload: Nl2AgentApplyLocalResourcesPayload
): Promise<Nl2AgentApplyLocalResourcesResponse> => {
  try {
    const response = await fetchWithAuth(
      API_ENDPOINTS.nl2agent.applyLocalResources(agentId),
      {
        method: "POST",
        body: JSON.stringify(payload),
      }
    );
    if (!response.ok) {
      const text = await response.text().catch(() => "");
      throw new Error(`Failed to apply local resources: ${response.status} ${text}`);
    }
    return response.json();
  } catch (error) {
    log.error("applyLocalResources failed", error);
    throw error;
  }
};

/**
 * Install a single official/web skill into the tenant.
 */
export const installWebSkill = async (
  agentId: number,
  payload: Nl2AgentInstallWebSkillPayload
): Promise<Nl2AgentInstallWebSkillResponse> => {
  try {
    const body: Nl2AgentInstallWebSkillPayload = {};
    if (typeof payload.skill_id === "number" && payload.skill_id > 0) {
      body.skill_id = payload.skill_id;
    }
    if (payload.skill_name) {
      body.skill_name = payload.skill_name;
    }

    const response = await fetchWithAuth(
      API_ENDPOINTS.nl2agent.installWebSkill(agentId),
      {
        method: "POST",
        body: JSON.stringify(body),
      }
    );
    if (!response.ok) {
      const text = await response.text().catch(() => "");
      throw new Error(`Failed to install web skill: ${response.status} ${text}`);
    }
    return response.json();
  } catch (error) {
    log.error("installWebSkill failed", error);
    throw error;
  }
};

/**
 * Finalize the draft agent by generating its full prompt set.
 */
export const finalizeNl2Agent = async (
  agentId: number,
  payload: Nl2AgentFinalizePayload
): Promise<Nl2AgentFinalizeResponse> => {
  try {
    const response = await fetchWithAuth(API_ENDPOINTS.nl2agent.finalize(agentId), {
      method: "POST",
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      const text = await response.text().catch(() => "");
      throw new Error(`Failed to finalize agent: ${response.status} ${text}`);
    }
    return response.json();
  } catch (error) {
    log.error("finalizeNl2Agent failed", error);
    throw error;
  }
};
