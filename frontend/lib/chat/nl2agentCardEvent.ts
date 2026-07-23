import type { components as Nl2AgentApiComponents } from "@/contracts/generated/nl2agent-api";

type Schemas = Nl2AgentApiComponents["schemas"];

export type StructuredNl2AgentCard = NonNullable<
  Schemas["Nl2AgentCardEnvelope"]["cards"]
>[number];
export type StructuredNl2AgentCardEnvelope = Schemas["Nl2AgentCardEnvelope"];
export type StructuredNl2AgentCardType = StructuredNl2AgentCard["card_type"];

export const parseStructuredNl2AgentEnvelope = (
  value: unknown
): StructuredNl2AgentCardEnvelope | undefined => {
  if (!value || typeof value !== "object" || Array.isArray(value)) return;
  const envelope = value as Record<string, unknown>;
  if (
    envelope.schema_version !== 1 ||
    typeof envelope.draft_agent_id !== "number" ||
    !Number.isInteger(envelope.draft_agent_id) ||
    envelope.draft_agent_id <= 0 ||
    typeof envelope.workflow_revision !== "number" ||
    !Number.isInteger(envelope.workflow_revision) ||
    envelope.workflow_revision < 0 ||
    !Array.isArray(envelope.cards)
  ) {
    return;
  }
  return envelope as unknown as StructuredNl2AgentCardEnvelope;
};

export const envelopeFromMessageMetadata = (
  messageType: unknown,
  metadata: unknown
): StructuredNl2AgentCardEnvelope | undefined => {
  if (
    messageType !== "nl2agent_card" ||
    !metadata ||
    typeof metadata !== "object" ||
    Array.isArray(metadata)
  ) {
    return;
  }
  return parseStructuredNl2AgentEnvelope(
    (metadata as Record<string, unknown>).nl2agent_card
  );
};
