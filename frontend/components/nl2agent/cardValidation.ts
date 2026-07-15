export type Nl2AgentCardType =
  | "requirements_summary"
  | "model_selection"
  | "local_resources"
  | "web_mcp"
  | "web_skill"
  | "agent_identity"
  | "final_review";

export type Nl2AgentCardFailureReason =
  "truncated_fence" | "invalid_json" | "invalid_schema" | "missing_card";

export interface ValidatedNl2AgentCard {
  cardType: Nl2AgentCardType;
  language: string;
  payload: Record<string, unknown>;
  cardKey?: string;
  requiresRegistration: boolean;
}

export interface Nl2AgentCardValidationResult {
  cards: ValidatedNl2AgentCard[];
  failure?: {
    cardType: Nl2AgentCardType;
    reason: Nl2AgentCardFailureReason;
    cardKey?: string;
  };
}

const LANGUAGE_TO_TYPE: Record<string, Nl2AgentCardType> = {
  "nl2agent-requirements-summary": "requirements_summary",
  "nl2agent-model-selection": "model_selection",
  "nl2agent-local-resources": "local_resources",
  "nl2agent-web-mcp": "web_mcp",
  "nl2agent-web-mcps": "web_mcp",
  "nl2agent-web-skill": "web_skill",
  "nl2agent-web-skills": "web_skill",
  "nl2agent-agent-identity": "agent_identity",
  "nl2agent-finalize": "final_review",
};

const isRecord = (value: unknown): value is Record<string, any> =>
  Boolean(value) && typeof value === "object" && !Array.isArray(value);
const nonEmpty = (value: unknown) =>
  typeof value === "string" && value.trim().length > 0;
const positiveInteger = (value: unknown) =>
  Number.isInteger(Number(value)) && Number(value) > 0;

const payloadAgentIds = (payload: Record<string, any>): number[] => [
  ...(positiveInteger(payload.agent_id) ? [Number(payload.agent_id)] : []),
  ...(Array.isArray(payload.items)
    ? payload.items.flatMap((item: unknown) =>
        isRecord(item) && positiveInteger(item.agent_id)
          ? [Number(item.agent_id)]
          : []
      )
    : []),
];

const validAgentId = (
  payload: Record<string, any>,
  trustedDraftAgentId?: number | null
) => {
  const ids = payloadAgentIds(payload);
  if (trustedDraftAgentId != null) {
    return ids.every((id) => id === trustedDraftAgentId);
  }
  return ids.length > 0 && ids.every((id) => id === ids[0]);
};

const validLocalItem = (item: unknown, idField: "tool_id" | "skill_id") =>
  isRecord(item) && positiveInteger(item[idField]) && nonEmpty(item.name);

const validMcpItem = (item: unknown) => {
  if (
    !isRecord(item) ||
    !nonEmpty(item.recommendation_id) ||
    !nonEmpty(item.name)
  ) {
    return false;
  }
  if (
    !Array.isArray(item.install_options) ||
    item.install_options.length === 0
  ) {
    return false;
  }
  return item.install_options.every(
    (option: unknown) =>
      isRecord(option) && nonEmpty(option.option_id) && nonEmpty(option.type)
  );
};

const validSkillItem = (item: unknown) =>
  isRecord(item) &&
  nonEmpty(item.skill_name || item.name) &&
  (positiveInteger(item.skill_id) || nonEmpty(item.skill_name));

const validateSchema = (
  type: Nl2AgentCardType,
  payload: Record<string, any>
) => {
  switch (type) {
    case "requirements_summary":
      return [
        "goal",
        "audience_or_scenario",
        "primary_input",
        "expected_output",
        "key_constraints",
      ].every((field) => nonEmpty(payload[field]));
    case "model_selection":
      return true;
    case "local_resources":
      return (
        nonEmpty(payload.recommendation_batch_id) &&
        Array.isArray(payload.tools) &&
        payload.tools.every((item: unknown) =>
          validLocalItem(item, "tool_id")
        ) &&
        Array.isArray(payload.skills) &&
        payload.skills.every((item: unknown) =>
          validLocalItem(item, "skill_id")
        )
      );
    case "web_mcp": {
      const items = Array.isArray(payload.items) ? payload.items : [payload];
      return (
        nonEmpty(payload.recommendation_batch_id) && items.every(validMcpItem)
      );
    }
    case "web_skill": {
      const items = Array.isArray(payload.items) ? payload.items : [payload];
      return (
        nonEmpty(payload.recommendation_batch_id) && items.every(validSkillItem)
      );
    }
    case "agent_identity":
      return (
        nonEmpty(payload.display_name) &&
        payload.display_name.trim().length <= 50
      );
    case "final_review":
      return ["business_description", "duty_prompt", "greeting_message"].every(
        (field) => nonEmpty(payload[field])
      );
  }
};

export const validateNl2AgentCards = (
  content: string,
  trustedDraftAgentId?: number | null
): Nl2AgentCardValidationResult => {
  const opening = /```(nl2agent-[^\s`]+)[^\S\r\n]*\r?\n/gi;
  const cards: ValidatedNl2AgentCard[] = [];
  const seen = new Set<Nl2AgentCardType>();
  let match: RegExpExecArray | null;

  while ((match = opening.exec(content)) !== null) {
    const language = match[1].toLowerCase();
    const cardType = LANGUAGE_TO_TYPE[language];
    if (!cardType) continue;
    const bodyStart = opening.lastIndex;
    const closingIndex = content.indexOf("```", bodyStart);
    if (closingIndex < 0) {
      return { cards, failure: { cardType, reason: "truncated_fence" } };
    }
    opening.lastIndex = closingIndex + 3;
    let payload: Record<string, unknown>;
    try {
      const parsed = JSON.parse(content.slice(bodyStart, closingIndex).trim());
      if (!isRecord(parsed)) throw new Error("Card payload must be an object");
      payload = parsed;
    } catch {
      return { cards, failure: { cardType, reason: "invalid_json" } };
    }
    const cardKey = nonEmpty(payload.recommendation_batch_id)
      ? String(payload.recommendation_batch_id)
      : undefined;
    if (
      seen.has(cardType) ||
      !validAgentId(payload, trustedDraftAgentId) ||
      !validateSchema(cardType, payload)
    ) {
      return {
        cards,
        failure: { cardType, reason: "invalid_schema", cardKey },
      };
    }
    seen.add(cardType);
    cards.push({
      cardType,
      language,
      payload,
      cardKey,
      requiresRegistration: [
        "requirements_summary",
        "local_resources",
        "web_mcp",
        "web_skill",
      ].includes(cardType),
    });
  }
  return { cards };
};
