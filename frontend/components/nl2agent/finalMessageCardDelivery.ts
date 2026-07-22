import { MESSAGE_ROLES } from "@/const/chatConfig";
import type { ChatMessageType } from "@/types/chat";
import type { Nl2AgentSessionState } from "@/services/nl2agentService";
import {
  validateNl2AgentCards,
  type Nl2AgentCardType,
  type ValidatedNl2AgentCard,
} from "./cardValidation";

export type Nl2AgentOnlineCardType = Extract<
  Nl2AgentCardType,
  "web_mcp" | "web_skill"
>;

export type LatestNl2AgentOnlineCardKeys = Partial<
  Record<Nl2AgentOnlineCardType, string>
>;

const isOnlineCardType = (
  cardType: Nl2AgentCardType
): cardType is Nl2AgentOnlineCardType =>
  cardType === "web_mcp" || cardType === "web_skill";

export const nl2AgentOnlineCardIdentity = (
  cardType: Nl2AgentOnlineCardType,
  cardKey: string
) => `${cardType}:${cardKey}`;

export const resolveLatestNl2AgentOnlineCardKeys = (
  messages: readonly ChatMessageType[],
  trustedDraftAgentId?: number | null
): LatestNl2AgentOnlineCardKeys => {
  const latest: LatestNl2AgentOnlineCardKeys = {};

  for (const message of messages) {
    if (
      message.role !== MESSAGE_ROLES.ASSISTANT ||
      !message.isComplete ||
      trustedDraftAgentId == null
    ) {
      continue;
    }
    const validation = validateNl2AgentCards(
      message.finalAnswer || message.content || "",
      trustedDraftAgentId
    );
    if (validation.failure) continue;

    for (const card of validation.cards) {
      if (isOnlineCardType(card.cardType) && card.cardKey) {
        latest[card.cardType] = card.cardKey;
      }
    }
  }

  return latest;
};

export const EMPTY_NL2AGENT_ONLINE_CARD_IDENTITY_SIGNATURE = "[]";

export const resolveActionableNl2AgentOnlineCardIdentitySignature = (
  cards: readonly ValidatedNl2AgentCard[],
  latestCardKeys: LatestNl2AgentOnlineCardKeys,
  sessionState: Nl2AgentSessionState | undefined,
  interactionEnabled: boolean
): string => {
  const actionable: string[] = [];
  if (
    !interactionEnabled ||
    !sessionState ||
    sessionState.resource_review.online_configuration_confirmed
  ) {
    return EMPTY_NL2AGENT_ONLINE_CARD_IDENTITY_SIGNATURE;
  }

  const batches = sessionState.resource_review.recommendations ?? {};
  for (const card of cards) {
    if (
      !isOnlineCardType(card.cardType) ||
      !card.cardKey ||
      card.agentId !== sessionState.agent_id ||
      latestCardKeys[card.cardType] !== card.cardKey
    ) {
      continue;
    }
    const batch = batches[card.cardKey];
    const resourceType = card.cardType === "web_mcp" ? "mcp" : "skill";
    if (batch?.resource_type === resourceType && batch.status === "presented") {
      actionable.push(nl2AgentOnlineCardIdentity(card.cardType, card.cardKey));
    }
  }

  return actionable.length
    ? JSON.stringify(actionable.sort())
    : EMPTY_NL2AGENT_ONLINE_CARD_IDENTITY_SIGNATURE;
};

export const parseNl2AgentOnlineCardIdentitySignature = (
  signature: string
): ReadonlySet<string> => {
  try {
    const parsed: unknown = JSON.parse(signature);
    return new Set(
      Array.isArray(parsed)
        ? parsed.filter((value): value is string => typeof value === "string")
        : []
    );
  } catch {
    return new Set();
  }
};

export const isNl2AgentCardExplicitlyInteractive = (
  card: ValidatedNl2AgentCard | undefined,
  interactiveCardIdentities: ReadonlySet<string> | undefined
) =>
  Boolean(
    card &&
    isOnlineCardType(card.cardType) &&
    card.cardKey &&
    interactiveCardIdentities?.has(
      nl2AgentOnlineCardIdentity(card.cardType, card.cardKey)
    )
  );

export interface Nl2AgentCardPresentationInput {
  isComplete: boolean;
  isStreaming: boolean;
  hasMessageId: boolean;
  hasValidationFailure: boolean;
  isLatestMessage: boolean;
  readOnly: boolean;
}

export const resolveNl2AgentCardPresentation = ({
  isComplete,
  isStreaming,
  hasMessageId,
  hasValidationFailure,
  isLatestMessage,
  readOnly,
}: Nl2AgentCardPresentationInput): {
  renderMode: "placeholder" | "readonly" | "interactive";
  registrationEnabled: boolean;
} => {
  const displayReady = isComplete && !hasValidationFailure;
  const deliveryReady = displayReady && hasMessageId && !isStreaming;
  return {
    renderMode: !displayReady
      ? "placeholder"
      : readOnly || !isLatestMessage
        ? "readonly"
        : "interactive",
    registrationEnabled: deliveryReady && !readOnly && isLatestMessage,
  };
};
