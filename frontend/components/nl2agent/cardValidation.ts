import Ajv, { type ValidateFunction } from "ajv";

import cardSchema from "@/contracts/generated/nl2agent-card.schema.json";
import type {
  AgentIdentityCardPayload,
  FinalReviewCardPayload,
  LocalResourcesCardPayload,
  ModelSelectionCardPayload,
  RequirementsSummaryCardPayload,
  WebMcpCardPayload,
  WebMcpListCardPayload,
  WebSkillCardPayload,
  WebSkillListCardPayload,
} from "./cardPayloadTypes";

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

interface Nl2AgentCardDefinitionMap {
  "nl2agent-requirements-summary": {
    cardType: "requirements_summary";
    payload: RequirementsSummaryCardPayload;
  };
  "nl2agent-model-selection": {
    cardType: "model_selection";
    payload: ModelSelectionCardPayload;
  };
  "nl2agent-local-resources": {
    cardType: "local_resources";
    payload: LocalResourcesCardPayload;
  };
  "nl2agent-web-mcp": {
    cardType: "web_mcp";
    payload: WebMcpCardPayload;
  };
  "nl2agent-web-mcps": {
    cardType: "web_mcp";
    payload: WebMcpListCardPayload;
  };
  "nl2agent-web-skill": {
    cardType: "web_skill";
    payload: WebSkillCardPayload;
  };
  "nl2agent-web-skills": {
    cardType: "web_skill";
    payload: WebSkillListCardPayload;
  };
  "nl2agent-agent-identity": {
    cardType: "agent_identity";
    payload: AgentIdentityCardPayload;
  };
  "nl2agent-finalize": {
    cardType: "final_review";
    payload: FinalReviewCardPayload;
  };
}

export type Nl2AgentCardLanguage = keyof Nl2AgentCardDefinitionMap;

interface ValidatedNl2AgentCardBase {
  agentId: number;
  cardKey?: string;
  requiresRegistration: boolean;
}

export type ValidatedNl2AgentCard = {
  [Language in Nl2AgentCardLanguage]: ValidatedNl2AgentCardBase &
    Nl2AgentCardDefinitionMap[Language] & { language: Language };
}[Nl2AgentCardLanguage];

export interface Nl2AgentCardValidationResult {
  cards: ValidatedNl2AgentCard[];
  failure?: {
    cardType: Nl2AgentCardType;
    reason: Nl2AgentCardFailureReason;
    cardKey?: string;
    agentIdError?: "missing" | "mismatch";
  };
}

const LANGUAGE_TO_TYPE: {
  [
    Language in Nl2AgentCardLanguage
  ]: Nl2AgentCardDefinitionMap[Language]["cardType"];
} = {
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

const getSchemaValidator = (cardType: Nl2AgentCardType) => {
  const schemaId = `${cardSchema.$id}#/$defs/${cardType}`;
  const validator = ajv.getSchema(schemaId);
  if (!validator) throw new Error(`Missing NL2AGENT card schema: ${cardType}`);
  return validator;
};

const schemaValidators: Record<Nl2AgentCardType, ValidateFunction> = {
  requirements_summary: getSchemaValidator("requirements_summary"),
  model_selection: getSchemaValidator("model_selection"),
  local_resources: getSchemaValidator("local_resources"),
  web_mcp: getSchemaValidator("web_mcp"),
  web_skill: getSchemaValidator("web_skill"),
  agent_identity: getSchemaValidator("agent_identity"),
  final_review: getSchemaValidator("final_review"),
};

const isNl2AgentCardLanguage = (
  language: string
): language is Nl2AgentCardLanguage => language in LANGUAGE_TO_TYPE;

const isRecord = (value: unknown): value is Record<string, unknown> =>
  Boolean(value) && typeof value === "object" && !Array.isArray(value);

const positiveInteger = (value: unknown) =>
  Number.isInteger(Number(value)) && Number(value) > 0;

const payloadAgentIds = (payload: Record<string, unknown>): number[] => [
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
  payload: Record<string, unknown>,
  trustedDraftAgentId?: number | null
):
  | { agentId: number; error?: never }
  | { agentId?: never; error: "missing" | "mismatch" } => {
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

const cardKeyFromPayload = (payload: Record<string, unknown>) =>
  typeof payload.recommendation_batch_id === "string" &&
  payload.recommendation_batch_id.trim()
    ? payload.recommendation_batch_id
    : undefined;

const payloadMatchesLanguage = (
  language: Nl2AgentCardLanguage,
  payload: Record<string, unknown>
) => {
  if (language === "nl2agent-web-mcps" || language === "nl2agent-web-skills") {
    return Array.isArray(payload.items);
  }
  if (language === "nl2agent-web-mcp" || language === "nl2agent-web-skill") {
    return !Object.hasOwn(payload, "items");
  }
  return true;
};

const createValidatedCard = <Language extends Nl2AgentCardLanguage>(
  language: Language,
  payload: Record<string, unknown>,
  agentId: number,
  cardKey: string | undefined
): ValidatedNl2AgentCard =>
  // This is the only trust boundary: AJV and payloadMatchesLanguage have
  // established the payload member selected by the normalized language.
  ({
    cardType: LANGUAGE_TO_TYPE[language],
    language,
    payload,
    agentId,
    cardKey,
    requiresRegistration: REGISTRATION_CARD_TYPES.has(
      LANGUAGE_TO_TYPE[language]
    ),
  }) as ValidatedNl2AgentCard;

export const parseNl2AgentCard = (
  language: string,
  content: string,
  trustedDraftAgentId?: number | null
): Nl2AgentCardValidationResult => {
  const normalizedLanguage = language.trim().toLowerCase();
  if (!isNl2AgentCardLanguage(normalizedLanguage)) return { cards: [] };
  const cardType = LANGUAGE_TO_TYPE[normalizedLanguage];

  let payload: Record<string, unknown>;
  try {
    const parsed = JSON.parse(content.trim());
    if (!isRecord(parsed)) throw new Error("Card payload must be an object");
    payload = parsed;
  } catch {
    return { cards: [], failure: { cardType, reason: "invalid_json" } };
  }

  const cardKey = cardKeyFromPayload(payload);
  const resolvedAgent = resolveAgentId(payload, trustedDraftAgentId);
  if (
    resolvedAgent.error ||
    !schemaValidators[cardType](payload) ||
    !payloadMatchesLanguage(normalizedLanguage, payload)
  ) {
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
        ...createValidatedCard(
          normalizedLanguage,
          payload,
          resolvedAgent.agentId,
          cardKey
        ),
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
    if (!isNl2AgentCardLanguage(language)) continue;
    const cardType = LANGUAGE_TO_TYPE[language];
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
