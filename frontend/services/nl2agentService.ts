/** Typed NL2AGENT lifecycle, read, and unified action client. */

import type { components as Nl2AgentApiComponents } from "@/contracts/generated/nl2agent-api";
import { fetchWithAuth } from "@/lib/auth";
import { API_ENDPOINTS, ApiError } from "@/services/api";

type Nl2AgentApiSchemas = Nl2AgentApiComponents["schemas"];

export type Nl2AgentActionRequest =
  | Nl2AgentApiSchemas["Nl2AgentConfirmRequirementsActionRequest"]
  | Nl2AgentApiSchemas["Nl2AgentSaveModelSelectionActionRequest"]
  | Nl2AgentApiSchemas["Nl2AgentApplyLocalResourcesActionRequest"]
  | Nl2AgentApiSchemas["Nl2AgentSkipLocalResourcesActionRequest"]
  | Nl2AgentApiSchemas["Nl2AgentInstallMcpActionRequest"]
  | Nl2AgentApiSchemas["Nl2AgentBindMcpToolsActionRequest"]
  | Nl2AgentApiSchemas["Nl2AgentSkipMcpToolsActionRequest"]
  | Nl2AgentApiSchemas["Nl2AgentInstallWebSkillActionRequest"]
  | Nl2AgentApiSchemas["Nl2AgentCompleteOnlineConfigurationActionRequest"]
  | Nl2AgentApiSchemas["Nl2AgentSaveIdentityActionRequest"]
  | Nl2AgentApiSchemas["Nl2AgentFinalizeActionRequest"];

type DistributiveOmit<T, K extends PropertyKey> = T extends unknown
  ? Omit<T, K>
  : never;

export type Nl2AgentActionDraft = DistributiveOmit<
  Nl2AgentActionRequest,
  "action_id" | "expected_revision"
>;
export type Nl2AgentActionResponse =
  Nl2AgentApiSchemas["Nl2AgentActionResponse"];
export type Nl2AgentActionType = Nl2AgentActionRequest["action"];
export type Nl2AgentRequirementsSummary =
  Nl2AgentApiSchemas["Nl2AgentRequirementsSummaryPayload"];
export type Nl2AgentFinalizePayload =
  Nl2AgentApiSchemas["Nl2AgentFinalizeActionPayload"];
export type LocalToolParameterSchema =
  Nl2AgentApiSchemas["Nl2AgentToolParameterSchema"];
export type Nl2AgentSessionState =
  Nl2AgentApiSchemas["Nl2AgentSessionStateResponse"];
export type Nl2AgentSessionStartResponse =
  Nl2AgentApiSchemas["Nl2AgentSessionStartResponse"];
export type Nl2AgentSessionSummary =
  Nl2AgentApiSchemas["Nl2AgentSessionSummaryResponse"];
export type Nl2AgentWebSkillConfiguration =
  Nl2AgentApiSchemas["Nl2AgentWebSkillConfigurationResponse"];

export class Nl2AgentRequestError extends Error {
  readonly status: number;
  readonly code?: string;
  readonly details?: unknown;

  constructor(
    message: string,
    status: number,
    code?: string,
    details?: unknown
  ) {
    super(message);
    this.name = "Nl2AgentRequestError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

const throwNl2AgentRequestError = async (
  response: Response
): Promise<never> => {
  const bodyText = await response.text().catch(() => "");
  let message = bodyText;
  let code: string | undefined;
  let details: unknown;
  try {
    const body: unknown = JSON.parse(bodyText);
    if (body && typeof body === "object" && !Array.isArray(body)) {
      const errorBody = body as Record<string, unknown>;
      if (typeof errorBody.message === "string") message = errorBody.message;
      else if (typeof errorBody.detail === "string") message = errorBody.detail;
      if (typeof errorBody.code === "string") code = errorBody.code;
      details = errorBody.details;
    }
  } catch {
    // Plain-text error responses are already suitable for display.
  }
  throw new Nl2AgentRequestError(
    message || `NL2AGENT request failed with status ${response.status}.`,
    response.status,
    code,
    details
  );
};

export const isNl2AgentWorkflowConflict = (
  error: unknown
): error is Nl2AgentRequestError =>
  error instanceof Nl2AgentRequestError && error.status === 409;

export const isNl2AgentStaleCard = (
  error: unknown
): error is Nl2AgentRequestError =>
  error instanceof Nl2AgentRequestError &&
  error.status === 409 &&
  error.code === "030203";

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

export const resolveNl2AgentSessionByConversation = async (
  conversationId: number
): Promise<Nl2AgentSessionSummary | null> => {
  try {
    const response = await fetchWithAuth(
      API_ENDPOINTS.nl2agent.sessionByConversation(conversationId)
    );
    if (!response.ok) await throwNl2AgentRequestError(response);
    return response.json();
  } catch (error) {
    if (error instanceof ApiError && String(error.code) === "030201") {
      return null;
    }
    throw error;
  }
};

export const resolveNl2AgentSessionByAgent = async (
  agentId: number
): Promise<Nl2AgentSessionSummary | null> => {
  const response = await fetchWithAuth(
    API_ENDPOINTS.nl2agent.sessionByAgent(agentId)
  );
  if (!response.ok) await throwNl2AgentRequestError(response);
  return response.json();
};

export const resumeNl2AgentSession = async (
  agentId: number
): Promise<Nl2AgentSessionSummary> => {
  const response = await fetchWithAuth(
    API_ENDPOINTS.nl2agent.resumeSession(agentId),
    { method: "POST" }
  );
  if (!response.ok) await throwNl2AgentRequestError(response);
  return response.json();
};

export const getNl2AgentSessionState = async (
  agentId: number
): Promise<Nl2AgentSessionState> => {
  const response = await fetchWithAuth(
    API_ENDPOINTS.nl2agent.sessionState(agentId)
  );
  if (!response.ok) await throwNl2AgentRequestError(response);
  return response.json();
};

export const dispatchNl2AgentAction = async (
  agentId: number,
  request: Nl2AgentActionRequest
): Promise<Nl2AgentActionResponse> => {
  const response = await fetchWithAuth(
    API_ENDPOINTS.nl2agent.actions(agentId),
    {
      method: "POST",
      body: JSON.stringify(request),
    }
  );
  if (!response.ok) await throwNl2AgentRequestError(response);
  return response.json();
};

export const getWebSkillConfiguration = async (
  agentId: number,
  payload: { skill_id?: number; skill_name?: string }
): Promise<Nl2AgentWebSkillConfiguration> => {
  const query = new URLSearchParams();
  if (typeof payload.skill_id === "number" && payload.skill_id > 0) {
    query.set("skill_id", String(payload.skill_id));
  }
  if (payload.skill_name) query.set("skill_name", payload.skill_name);
  const response = await fetchWithAuth(
    `${API_ENDPOINTS.nl2agent.webSkillConfiguration(agentId)}?${query.toString()}`
  );
  if (!response.ok) await throwNl2AgentRequestError(response);
  return response.json();
};

let pendingSessionStart: Promise<Nl2AgentSessionStartResponse> | null = null;

const requestNl2AgentSessionStart = async () => {
  const response = await fetchWithAuth(API_ENDPOINTS.nl2agent.sessionStart, {
    method: "POST",
  });
  if (!response.ok) await throwNl2AgentRequestError(response);
  return response.json() as Promise<Nl2AgentSessionStartResponse>;
};

export const startNl2AgentSession =
  (): Promise<Nl2AgentSessionStartResponse> => {
    if (pendingSessionStart !== null) return pendingSessionStart;
    pendingSessionStart = requestNl2AgentSessionStart().finally(() => {
      pendingSessionStart = null;
    });
    return pendingSessionStart;
  };
