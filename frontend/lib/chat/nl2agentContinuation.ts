import type {
  Nl2AgentActionResponse,
  Nl2AgentActionType,
} from "@/services/nl2agentService";

export interface Nl2AgentActionContext {
  actionId: string;
  action: Nl2AgentActionType;
  displayText: string;
  workflowRevision: number;
}

export const createNl2AgentActionContext = (
  response: Nl2AgentActionResponse,
  displayText: string
): Nl2AgentActionContext => ({
  actionId: response.action_id,
  action: response.action,
  displayText,
  workflowRevision: response.workflow_revision,
});

export const parseNl2AgentActionContext = (
  value: unknown
): Nl2AgentActionContext | undefined => {
  if (!value || typeof value !== "object" || Array.isArray(value)) return;
  const context = value as Record<string, unknown>;
  if (
    typeof context.actionId !== "string" ||
    context.actionId.trim().length === 0 ||
    typeof context.action !== "string" ||
    typeof context.displayText !== "string" ||
    context.displayText.trim().length === 0 ||
    typeof context.workflowRevision !== "number" ||
    !Number.isInteger(context.workflowRevision) ||
    context.workflowRevision < 0
  ) {
    return;
  }
  return context as unknown as Nl2AgentActionContext;
};

export const nl2AgentContinuationScopeKey = (
  conversationId?: number | null,
  draftAgentId?: number | null
): string => `${conversationId ?? "new"}:${draftAgentId ?? "none"}`;
