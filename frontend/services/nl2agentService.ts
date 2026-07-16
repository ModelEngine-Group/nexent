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

export type Nl2AgentSessionStartResponse =
  Nl2AgentApiSchemas["Nl2AgentSessionStartResponse"];

export type Nl2AgentApplyLocalResourcesPayload =
  Nl2AgentApiSchemas["Nl2AgentApplyLocalResourcesRequest"] & {
    tool_ids: number[];
    skill_ids: number[];
  };

export type Nl2AgentLocalResourceRegistrationResponse =
  Nl2AgentApiSchemas["Nl2AgentLocalRecommendationResponse"];

export type LocalToolParameterSchema =
  Nl2AgentApiSchemas["Nl2AgentToolParameterSchema"];

export type Nl2AgentRequirementsSummary =
  Nl2AgentApiSchemas["Nl2AgentRequirementsSummaryRequest"];

export const registerRequirementsSummary = async (
  agentId: number,
  summary: Nl2AgentRequirementsSummary
): Promise<Nl2AgentApiSchemas["Nl2AgentRequirementsRegistrationResponse"]> => {
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
): Promise<Nl2AgentApiSchemas["Nl2AgentRequirementsConfirmationResponse"]> => {
  const response = await fetchWithAuth(
    API_ENDPOINTS.nl2agent.confirmRequirements(agentId),
    { method: "POST", body: JSON.stringify({ fingerprint }) }
  );
  if (!response.ok) throw new Error(await response.text());
  return response.json();
};

export type Nl2AgentCardDeliveryResponse =
  Nl2AgentApiSchemas["Nl2AgentCardDeliveryResponse"];

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
): Promise<Nl2AgentApiSchemas["Nl2AgentLocalSkipResponse"]> => {
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
): Promise<Nl2AgentApiSchemas["Nl2AgentOnlineRecommendationResponse"]> => {
  const response = await fetchWithAuth(
    API_ENDPOINTS.nl2agent.registerOnlineRecommendations(agentId),
    { method: "POST", body: JSON.stringify(payload) }
  );
  if (!response.ok) throw new Error(await response.text());
  return response.json();
};

export const completeOnlineResourceConfiguration = async (
  agentId: number
): Promise<Nl2AgentApiSchemas["Nl2AgentOnlineConfigurationResponse"]> => {
  const response = await fetchWithAuth(
    API_ENDPOINTS.nl2agent.completeOnlineConfiguration(agentId),
    { method: "POST" }
  );
  if (!response.ok) throw new Error(await response.text());
  return response.json();
};

export type Nl2AgentSessionState =
  Nl2AgentApiSchemas["Nl2AgentSessionStateResponse"];

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
): Promise<Nl2AgentApiSchemas["Nl2AgentIdentityResponse"]> => {
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

export type Nl2AgentApplyLocalResourcesResponse =
  Nl2AgentApiSchemas["Nl2AgentApplyLocalResourcesResponse"];

export const selectNl2AgentModels = async (
  agentId: number,
  primaryModelId: number,
  fallbackModelIds: number[]
): Promise<Nl2AgentApiSchemas["Nl2AgentModelSelectionResponse"]> => {
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
): Promise<Nl2AgentApiSchemas["Nl2AgentMcpInstallResponse"]> => {
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
): Promise<Nl2AgentApiSchemas["Nl2AgentMcpBindToolsResponse"]> => {
  const response = await fetchWithAuth(
    API_ENDPOINTS.nl2agent.bindMcpTools(agentId, mcpId),
    { method: "POST", body: JSON.stringify({ tool_ids: toolIds }) }
  );
  if (!response.ok) throw new Error(await response.text());
  return response.json();
};

export const skipNl2AgentMcpTools = async (
  agentId: number,
  mcpId: number
): Promise<Nl2AgentApiSchemas["Nl2AgentMcpSkipToolsResponse"]> => {
  const response = await fetchWithAuth(
    API_ENDPOINTS.nl2agent.skipMcpTools(agentId, mcpId),
    { method: "POST" }
  );
  if (!response.ok) throw new Error(await response.text());
  return response.json();
};

export type Nl2AgentInstallWebSkillResponse =
  Nl2AgentApiSchemas["Nl2AgentWebSkillInstallResponse"];

export type Nl2AgentInstallWebSkillPayload =
  Nl2AgentApiSchemas["Nl2AgentInstallWebSkillRequest"];

export type Nl2AgentFinalizePayload =
  Nl2AgentApiSchemas["Nl2AgentFinalizeRequest"];

export type Nl2AgentFinalizeResponse =
  Nl2AgentApiSchemas["Nl2AgentFinalizeResponse"];

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
