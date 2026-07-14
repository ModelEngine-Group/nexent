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

export const getAvailablePlatformLlms = async (): Promise<
  Array<{ id: number; displayName: string }>
> => {
  const response = await fetchWithAuth(API_ENDPOINTS.model.llmModelList);
  const result = await response.json();
  if (!response.ok || !Array.isArray(result.data)) {
    throw new Error("Failed to load available platform LLMs.");
  }
  return result.data
    .filter((model: any) => model.connect_status === "available")
    .map((model: any) => ({
      id: Number(model.model_id),
      displayName: model.display_name || model.model_name,
    }))
    .filter(
      (model: { id: number }) => Number.isInteger(model.id) && model.id > 0
    );
};

export interface Nl2AgentSessionStartResponse {
  nl2agent_agent_id: number;
  draft_agent_id: number;
  conversation_id: number;
  draft_name: string;
  /** Backward-compatible alias if older deployments still return it. */
  agent_id?: number;
}

export interface Nl2AgentApplyLocalResourcesPayload {
  recommendation_batch_id: string;
  tool_ids: number[];
  skill_ids: number[];
}

export const registerLocalResourceRecommendations = async (
  agentId: number,
  payload: Nl2AgentApplyLocalResourcesPayload
) => {
  const response = await fetchWithAuth(
    API_ENDPOINTS.nl2agent.registerLocalResources(agentId),
    { method: "POST", body: JSON.stringify(payload) }
  );
  if (!response.ok) throw new Error(await response.text());
  return response.json();
};

export const skipLocalResourceRecommendations = async (
  agentId: number,
  recommendationBatchId: string
) => {
  const response = await fetchWithAuth(
    API_ENDPOINTS.nl2agent.skipLocalResources(agentId),
    {
      method: "POST",
      body: JSON.stringify({ recommendation_batch_id: recommendationBatchId }),
    }
  );
  if (!response.ok) throw new Error(await response.text());
  return response.json();
};

export const registerOnlineResourceRecommendations = async (
  agentId: number,
  payload: {
    recommendation_batch_id: string;
    resource_type: "mcp" | "skill";
    item_keys: string[];
  }
) => {
  const response = await fetchWithAuth(
    API_ENDPOINTS.nl2agent.registerOnlineRecommendations(agentId),
    { method: "POST", body: JSON.stringify(payload) }
  );
  if (!response.ok) throw new Error(await response.text());
  return response.json();
};

export const completeOnlineResourceConfiguration = async (
  agentId: number
): Promise<{
  agent_id: number;
  online_configuration_confirmed: boolean;
  completed_batch_ids: string[];
  chat_injection_text: string;
}> => {
  const response = await fetchWithAuth(
    API_ENDPOINTS.nl2agent.completeOnlineConfiguration(agentId),
    { method: "POST" }
  );
  if (!response.ok) throw new Error(await response.text());
  return response.json();
};

export interface Nl2AgentSessionState {
  agent_id: number;
  display_name?: string;
  internal_name: string;
  identity_confirmed: boolean;
  business_logic_model_id?: number;
  model_ids: number[];
  tools: Array<{ tool_id: number; [key: string]: unknown }>;
  skills: Array<{ skill_id: number; [key: string]: unknown }>;
  resource_review: {
    identity_confirmed: boolean;
    recommendation_batches: Record<string, unknown>;
    online_recommendation_batches: Record<
      string,
      {
        resource_type: "mcp" | "skill";
        item_keys: string[];
        status: "recommendations_ready" | "completed";
      }
    >;
    online_configuration_confirmed: boolean;
    mcp_workflows: Record<
      string,
      {
        recommendation_id: string;
        option_id?: string;
        status?:
          | "configuration_required"
          | "installing"
          | "connected"
          | "tools_bound"
          | "binding_skipped"
          | "failed";
        mcp_id?: number;
        discovered_tool_ids?: number[];
        bound_tool_ids?: number[];
        discovered_tools?: Array<{
          tool_id: number;
          name: string;
          description?: string;
        }>;
        error?: string;
      }
    >;
  };
}

export const getNl2AgentSessionState = async (
  agentId: number
): Promise<Nl2AgentSessionState> => {
  const response = await fetchWithAuth(
    API_ENDPOINTS.nl2agent.sessionState(agentId)
  );
  if (!response.ok) throw new Error(await response.text());
  return response.json();
};

export const saveNl2AgentIdentity = async (
  agentId: number,
  displayName: string
): Promise<{
  agent_id: number;
  display_name: string;
  internal_name: string;
  identity_confirmed: boolean;
  chat_injection_text?: string;
}> => {
  const response = await fetchWithAuth(
    API_ENDPOINTS.nl2agent.saveIdentity(agentId),
    {
      method: "PUT",
      body: JSON.stringify({ display_name: displayName }),
    }
  );
  if (!response.ok) throw new Error(await response.text());
  return response.json();
};

export interface Nl2AgentApplyLocalResourcesResponse {
  bound_tool_count: number;
  bound_skill_count: number;
  tool_ids: number[];
  skill_ids: number[];
  chat_injection_text?: string;
}

export const selectNl2AgentModels = async (
  agentId: number,
  primaryModelId: number,
  fallbackModelIds: number[]
) => {
  const response = await fetchWithAuth(
    API_ENDPOINTS.nl2agent.selectModels(agentId),
    {
      method: "PUT",
      body: JSON.stringify({
        primary_model_id: primaryModelId,
        fallback_model_ids: fallbackModelIds,
      }),
    }
  );
  if (!response.ok) throw new Error(await response.text());
  return response.json();
};

export const installNl2AgentMcp = async (
  agentId: number,
  payload: {
    recommendation_id: string;
    option_id: string;
    config_values: Record<string, unknown>;
  }
) => {
  const response = await fetchWithAuth(
    API_ENDPOINTS.nl2agent.installMcp(agentId),
    {
      method: "POST",
      body: JSON.stringify(payload),
    }
  );
  if (!response.ok) throw new Error(await response.text());
  return response.json();
};

export const bindNl2AgentMcpTools = async (
  agentId: number,
  mcpId: number,
  toolIds: number[]
) => {
  const response = await fetchWithAuth(
    API_ENDPOINTS.nl2agent.bindMcpTools(agentId, mcpId),
    { method: "POST", body: JSON.stringify({ tool_ids: toolIds }) }
  );
  if (!response.ok) throw new Error(await response.text());
  return response.json();
};

export const skipNl2AgentMcpTools = async (agentId: number, mcpId: number) => {
  const response = await fetchWithAuth(
    API_ENDPOINTS.nl2agent.skipMcpTools(agentId, mcpId),
    { method: "POST" }
  );
  if (!response.ok) throw new Error(await response.text());
  return response.json();
};

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
export const startNl2AgentSession =
  async (): Promise<Nl2AgentSessionStartResponse> => {
    const response = await fetchWithAuth(API_ENDPOINTS.nl2agent.sessionStart, {
      method: "POST",
    });
    if (!response.ok) {
      const text = await response.text().catch(() => "");
      throw new Error(
        `Failed to start NL2AGENT session: ${response.status} ${text}`
      );
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
      throw new Error(
        `Failed to apply local resources: ${response.status} ${text}`
      );
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
      throw new Error(
        `Failed to install web skill: ${response.status} ${text}`
      );
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
    const response = await fetchWithAuth(
      API_ENDPOINTS.nl2agent.finalize(agentId),
      {
        method: "POST",
        body: JSON.stringify(payload),
      }
    );
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
