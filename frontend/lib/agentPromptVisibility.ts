import type { TFunction } from "i18next";

/** Agent-like object that may include prompts_hidden from /agent/search_info. */
export type AgentPromptVisibilitySource = {
  prompts_hidden?: boolean;
  duty_prompt?: string | null;
  constraint_prompt?: string | null;
  few_shots_prompt?: string | null;
};

export function isAgentPromptsHidden(
  agent: AgentPromptVisibilitySource | null | undefined
): boolean {
  return agent?.prompts_hidden === true;
}

/**
 * Render prompt field content for read-only views.
 * When prompts are hidden, show a permission message instead of None/empty.
 */
export function renderAgentPromptFieldValue(
  agent: AgentPromptVisibilitySource | null | undefined,
  field: "duty_prompt" | "constraint_prompt" | "few_shots_prompt",
  t: TFunction,
  noneLabel?: string
): string {
  if (isAgentPromptsHidden(agent)) {
    return t("agent.prompts.noPermission", "You do not have permission to view prompts.");
  }
  const value = agent?.[field];
  if (value == null || value === "") {
    return noneLabel ?? t("common.none", "None");
  }
  return value;
}
