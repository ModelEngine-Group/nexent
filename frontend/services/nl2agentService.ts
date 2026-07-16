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
import type { components as Nl2AgentApiComponents } from "@/contracts/generated/nl2agent-api";
import type {
  Nl2AgentCardFailureReason,
  Nl2AgentCardType,
} from "@/components/nl2agent/cardValidation";

type Nl2AgentApiSchemas = Nl2AgentApiComponents["schemas"];

export const getAvailablePlatformLlms = async (): Promise<
  Array<{ id: number; displayName: string }>
> => {
  const response = await fetchWithAuth(API_ENDPOINTS.model.llmModelList);
  const result = await response.json();
  if (!response.ok || !Array.isArray(result.data)) {
    throw new Error("Failed to load available platform LLMs.");
  }
  return (result.data as unknown[])
    .filter(
      (model: unknown): model is Record<string, unknown> =>
        Boolean(model) &&
        typeof model === "object" &&
        !Array.isArray(model) &&
        (model as Record<string, unknown>).connect_status === "available"
    )
    .map((model) => ({
      id: Number(model.model_id),
      displayName: String(model.display_name || model.model_name || ""),
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

export type Nl2AgentApplyLocalResourcesPayload =
  Nl2AgentApiSchemas["Nl2AgentApplyLocalResourcesRequest"] & {
    tool_ids: number[];
    skill_ids: number[];
  };

export interface Nl2AgentLocalResourceRegistrationResponse {
  recommendation_batch_id: string;
  status: string;
  tool_ids: number[];
  skill_ids: number[];
  tool_parameter_schemas: Record<string, LocalToolParameterSchema[]>;
}

export interface LocalToolParameterSchema {
  name: string;
  type?: string;
  description?: string;
  default?: unknown;
  required?: boolean;
  optional?: boolean;
  isSecret?: boolean;
  is_secret?: boolean;
  choices?: unknown[];
}

export type Nl2AgentRequirementsSummary =
  Nl2AgentApiSchemas["Nl2AgentRequirementsSummaryRequest"];

export const registerRequirementsSummary = async (
  agentId: number,
  summary: Nl2AgentRequirementsSummary
): Promise<{
  agent_id: number;
  status: "collecting" | "awaiting_confirmation" | "confirmed";
  summary: Nl2AgentRequirementsSummary;
  fingerprint: string;
  is_current: boolean;
}> => {
  const response = await fetchWithAuth(
    API_ENDPOINTS.nl2agent.registerRequirements(agentId),
    { method: "POST", body: JSON.stringify(summary) }
  );
  if (!response.ok) throw new Error(await response.text());
  return response.json();
};

export const confirmRequirementsSummary = async (
  agentId: number,
  fingerprint: string
): Promise<{
  agent_id: number;
  status: "confirmed";
  fingerprint: string;
  chat_injection_text?: string;
}> => {
  const response = await fetchWithAuth(
    API_ENDPOINTS.nl2agent.confirmRequirements(agentId),
    { method: "POST", body: JSON.stringify({ fingerprint }) }
  );
  if (!response.ok) throw new Error(await response.text());
  return response.json();
};

export interface Nl2AgentCardDeliveryResponse {
  agent_id: number;
  card_type: Nl2AgentCardType;
  status: "rendered" | "failed";
  card_key?: string;
  reason?: Nl2AgentCardFailureReason;
  retry_count: number;
  auto_retry_allowed: boolean;
  chat_injection_text?: string;
}

export const reportNl2AgentCardDelivery = async (
  agentId: number,
  payload: Nl2AgentApiSchemas["Nl2AgentCardDeliveryRequest"]
): Promise<Nl2AgentCardDeliveryResponse> => {
  const response = await fetchWithAuth(
    API_ENDPOINTS.nl2agent.cardDelivery(agentId),
    { method: "POST", body: JSON.stringify(payload) }
  );
  if (!response.ok) throw new Error(await response.text());
  return response.json();
};

export const registerLocalResourceRecommendations = async (
  agentId: number,
  payload: Nl2AgentApiSchemas["Nl2AgentRecommendationBatchRequest"]
): Promise<Nl2AgentLocalResourceRegistrationResponse> => {
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
  payload: Nl2AgentApiSchemas["Nl2AgentOnlineRecommendationBatchRequest"]
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
  schema_version: 2;
  revision: number;
  current_stage:
    | "requirements_collecting"
    | "requirements_confirmation"
    | "model_selection"
    | "local_resource_search"
    | "local_resource_review"
    | "online_resource_search"
    | "online_resource_review"
    | "agent_identity"
    | "final_review";
  expected_card_types: Nl2AgentCardType[];
  allowed_actions: string[];
  display_name?: string;
  internal_name: string;
  identity_confirmed: boolean;
  business_logic_model_id?: number;
  model_ids: number[];
  models: Array<{
    model_id: number;
    display_name?: string;
    role: "primary" | "fallback";
    valid: boolean;
  }>;
  tools: Array<{
    tool_id: number;
    name: string;
    source: string;
    origin: "local" | "online";
    [key: string]: unknown;
  }>;
  skills: Array<{
    skill_id: number;
    name: string;
    source: string;
    origin: "local" | "online";
    [key: string]: unknown;
  }>;
  invalid_references: Array<{
    reference_type: "model" | "tool" | "skill";
    reference_id: number;
    reason:
      | "not_found"
      | "not_llm"
      | "unavailable"
      | "name_missing"
      | "primary_not_in_runtime_models";
  }>;
  resource_review: {
    requirements_review: {
      status: "collecting" | "awaiting_confirmation" | "confirmed";
      summary: Nl2AgentRequirementsSummary | null;
      fingerprint: string;
    };
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
    card_delivery?: Record<
      string,
      {
        message_id: number;
        status: "rendered" | "failed";
        card_key?: string;
        reason?: string;
        retry_count: number;
      }
    >;
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
  payload: Nl2AgentApiSchemas["Nl2AgentMcpInstallRequest"]
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
  bound: boolean;
  installed_ids: number[];
  installed_names?: string[];
}

export type Nl2AgentInstallWebSkillPayload =
  Nl2AgentApiSchemas["Nl2AgentInstallWebSkillRequest"];

export type Nl2AgentFinalizePayload =
  Nl2AgentApiSchemas["Nl2AgentFinalizeRequest"];

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
 * Install a single official/web skill and bind it to the draft agent.
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
    const result: Nl2AgentInstallWebSkillResponse = await response.json();
    if (!result.installed || !result.bound) {
      throw new Error("The skill was not installed and bound to the draft.");
    }
    return result;
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
