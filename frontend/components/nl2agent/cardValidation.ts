import Ajv, { type ValidateFunction } from "ajv";

import cardSchema from "@/contracts/generated/nl2agent-card.schema.json";

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
  payload: Record<string, any>;
  agentId: number;
  cardKey?: string;
  requiresRegistration: boolean;
}

export interface Nl2AgentCardValidationResult {
  cards: ValidatedNl2AgentCard[];
  failure?: {
    cardType: Nl2AgentCardType;
    reason: Nl2AgentCardFailureReason;
    cardKey?: string;
    agentIdError?: "missing" | "mismatch";
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

const REGISTRATION_CARD_TYPES = new Set<Nl2AgentCardType>([
  "requirements_summary",
  "local_resources",
  "web_mcp",
  "web_skill",
]);

const ajv = new Ajv({ allErrors: true, strict: false });
ajv.addSchema(cardSchema);

const schemaValidators = Object.fromEntries(
  (Object.values(LANGUAGE_TO_TYPE) as Nl2AgentCardType[]).map((cardType) => {
    const schemaId = `${cardSchema.$id}#/$defs/${cardType}`;
    const validator = ajv.getSchema(schemaId);
    if (!validator)
      throw new Error(`Missing NL2AGENT card schema: ${cardType}`);
    return [cardType, validator];
  })
) as Record<Nl2AgentCardType, ValidateFunction>;

const isRecord = (value: unknown): value is Record<string, any> =>
  Boolean(value) && typeof value === "object" && !Array.isArray(value);

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

const resolveAgentId = (
  payload: Record<string, any>,
  trustedDraftAgentId?: number | null
): { agentId?: number; error?: "missing" | "mismatch" } => {
  const ids = payloadAgentIds(payload);
  if (trustedDraftAgentId != null) {
    return ids.every((id) => id === trustedDraftAgentId)
      ? { agentId: trustedDraftAgentId }
      : { error: "mismatch" };
  }
  if (ids.length === 0) return { error: "missing" };
  return ids.every((id) => id === ids[0])
    ? { agentId: ids[0] }
    : { error: "mismatch" };
};

const cardKeyFromPayload = (payload: Record<string, any>) =>
  typeof payload.recommendation_batch_id === "string" &&
  payload.recommendation_batch_id.trim()
    ? payload.recommendation_batch_id
    : undefined;

export const parseNl2AgentCard = (
  language: string,
  content: string,
  trustedDraftAgentId?: number | null
): Nl2AgentCardValidationResult => {
  const normalizedLanguage = language.trim().toLowerCase();
  const cardType = LANGUAGE_TO_TYPE[normalizedLanguage];
  if (!cardType) return { cards: [] };

  let payload: Record<string, any>;
  try {
    const parsed = JSON.parse(content.trim());
    if (!isRecord(parsed)) throw new Error("Card payload must be an object");
    payload = parsed;
  } catch {
    return { cards: [], failure: { cardType, reason: "invalid_json" } };
  }

  const cardKey = cardKeyFromPayload(payload);
  const resolvedAgent = resolveAgentId(payload, trustedDraftAgentId);
  if (resolvedAgent.error || !schemaValidators[cardType](payload)) {
    return {
      cards: [],
      failure: {
        cardType,
        reason: "invalid_schema",
        cardKey,
        agentIdError: resolvedAgent.error,
      },
    };
  }

  return {
    cards: [
      {
        cardType,
        language: normalizedLanguage,
        payload,
        agentId: resolvedAgent.agentId as number,
        cardKey,
        requiresRegistration: REGISTRATION_CARD_TYPES.has(cardType),
      },
    ],
  };
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
    const parsed = parseNl2AgentCard(
      language,
      content.slice(bodyStart, closingIndex),
      trustedDraftAgentId
    );
    if (parsed.failure) return { cards, failure: parsed.failure };
    const card = parsed.cards[0];
    if (seen.has(cardType)) {
      return {
        cards,
        failure: {
          cardType,
          reason: "invalid_schema",
          cardKey: card.cardKey,
        },
      };
    }
    seen.add(cardType);
    cards.push(card);
  }
  return { cards };
};
