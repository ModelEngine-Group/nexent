export const NL2AGENT_AUTO_CONTINUE_PREFIX = "[[NL2AGENT_AUTO_CONTINUE]]";
export const NL2AGENT_CARD_RETRY_PREFIX = "[[NL2AGENT_CARD_RETRY]]";

export type Nl2AgentUserActionType =
  | "confirm_requirements"
  | "save_model_selection"
  | "apply_local_resources"
  | "skip_local_resources"
  | "complete_online_configuration"
  | "save_identity";

const NL2AGENT_USER_ACTION_TYPES: readonly Nl2AgentUserActionType[] = [
  "confirm_requirements",
  "save_model_selection",
  "apply_local_resources",
  "skip_local_resources",
  "complete_online_configuration",
  "save_identity",
];

export interface Nl2AgentUserAction {
  actionId: string;
  action: Nl2AgentUserActionType;
  displayText: string;
}

export type Nl2AgentUserActionDraft = Omit<Nl2AgentUserAction, "actionId">;

export const createNl2AgentUserAction = (
  draft: Nl2AgentUserActionDraft
): Nl2AgentUserAction => ({
  ...draft,
  actionId: crypto.randomUUID(),
});

export const parseNl2AgentUserAction = (
  value: unknown
): Nl2AgentUserAction | undefined => {
  if (!value || typeof value !== "object" || Array.isArray(value)) return;
  const action = value as Record<string, unknown>;
  if (
    typeof action.actionId !== "string" ||
    action.actionId.trim().length === 0 ||
    typeof action.action !== "string" ||
    typeof action.displayText !== "string" ||
    action.displayText.trim().length === 0 ||
    !NL2AGENT_USER_ACTION_TYPES.includes(
      action.action as Nl2AgentUserActionType
    )
  ) {
    return;
  }
  return action as unknown as Nl2AgentUserAction;
};

export const isNl2AgentAutoContinueText = (value: unknown): boolean =>
  [NL2AGENT_AUTO_CONTINUE_PREFIX, NL2AGENT_CARD_RETRY_PREFIX].some((prefix) =>
    String(value || "").startsWith(prefix)
  );

export const nl2AgentContinuationScopeKey = (
  conversationId?: number | null,
  draftAgentId?: number | null
): string => `${conversationId ?? "new"}:${draftAgentId ?? "none"}`;
