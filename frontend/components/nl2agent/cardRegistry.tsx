"use client";

import React from "react";

import type { components as Nl2AgentApiComponents } from "@/contracts/generated/nl2agent-api";
import { AgentIdentityCard } from "./AgentIdentityCard";
import type {
  FinalReviewCardPayload,
  RequirementsSummaryCardPayload,
  WebSkillCardPayloadItem,
} from "./cardPayloadTypes";
import {
  toWebSkillCardItem,
  webSkillRecommendationKey,
} from "./cardPayloadTypes";
import { FinalizeCard } from "./FinalizeCard";
import { LocalResourcesCard } from "./LocalResourcesCard";
import { ModelSelectionCard } from "./ModelSelectionCard";
import { useNl2AgentWorkflow } from "./Nl2AgentWorkflowContext";
import { RequirementsSummaryCard } from "./RequirementsSummaryCard";
import { WebMcpCard } from "./WebMcpCard";
import type { WebMcpCardItem } from "./webMcpTypes";
import { WebSkillCard } from "./WebSkillCard";

type Schemas = Nl2AgentApiComponents["schemas"];
export type StructuredNl2AgentCard = NonNullable<
  Schemas["Nl2AgentCardEnvelope"]["cards"]
>[number];
export type StructuredNl2AgentCardEnvelope = Schemas["Nl2AgentCardEnvelope"];
export type StructuredNl2AgentCardType = StructuredNl2AgentCard["card_type"];

type StructuredCardRenderer = (
  card: StructuredNl2AgentCard,
  draftAgentId: number
) => React.ReactNode;

const OnlineRecommendationGroup: React.FC<{
  recommendationBatchId: string;
  resourceType: "mcp" | "skill";
  children: React.ReactNode;
}> = ({ recommendationBatchId, resourceType, children }) => {
  const workflow = useNl2AgentWorkflow();
  const batch =
    workflow.sessionState?.resource_review.recommendations?.[
      recommendationBatchId
    ];
  const completed =
    batch?.resource_type === resourceType && batch.status === "completed";
  return (
    <div className={completed ? "pointer-events-none opacity-60" : ""}>
      {children}
    </div>
  );
};

const renderRequirementsSummary: StructuredCardRenderer = (
  card,
  draftAgentId
) => {
  if (card.card_type !== "requirements_summary") return null;
  return (
    <RequirementsSummaryCard
      agentId={draftAgentId}
      summary={card.payload as RequirementsSummaryCardPayload}
    />
  );
};

const renderModelSelection: StructuredCardRenderer = (card, draftAgentId) =>
  card.card_type === "model_selection" ? (
    <ModelSelectionCard agentId={draftAgentId} />
  ) : null;

const renderLocalResources: StructuredCardRenderer = (card, draftAgentId) => {
  if (card.card_type !== "local_resources") return null;
  return (
    <LocalResourcesCard
      agentId={draftAgentId}
      recommendationBatchId={card.payload.recommendation_batch_id}
      tools={card.payload.tools.map((item) => ({
        ...item,
        kind: "tool" as const,
      }))}
      skills={card.payload.skills.map((item) => ({
        ...item,
        kind: "skill" as const,
      }))}
    />
  );
};

const renderWebMcp: StructuredCardRenderer = (card, draftAgentId) => {
  if (card.card_type !== "web_mcp") return null;
  const payload = card.payload;
  const recommendationBatchId = payload.recommendation_batch_id;
  const items = "items" in payload ? payload.items : [payload];
  return (
    <OnlineRecommendationGroup
      recommendationBatchId={recommendationBatchId}
      resourceType="mcp"
    >
      {items.map((item) => (
        <WebMcpCard
          key={item.recommendation_id}
          agentId={draftAgentId}
          recommendationBatchId={recommendationBatchId}
          item={item as WebMcpCardItem}
        />
      ))}
    </OnlineRecommendationGroup>
  );
};

const renderWebSkill: StructuredCardRenderer = (card, draftAgentId) => {
  if (card.card_type !== "web_skill") return null;
  const payload = card.payload;
  const recommendationBatchId = payload.recommendation_batch_id;
  const rawItems = "items" in payload ? payload.items : [payload];
  const items = rawItems.map((item) =>
    toWebSkillCardItem(item as WebSkillCardPayloadItem)
  );
  return (
    <OnlineRecommendationGroup
      recommendationBatchId={recommendationBatchId}
      resourceType="skill"
    >
      {items.map((item) => {
        const itemKey = webSkillRecommendationKey(item);
        return (
          <WebSkillCard
            key={itemKey}
            agentId={draftAgentId}
            recommendationBatchId={recommendationBatchId}
            itemKey={itemKey}
            item={item}
          />
        );
      })}
    </OnlineRecommendationGroup>
  );
};

const renderAgentIdentity: StructuredCardRenderer = (card, draftAgentId) => {
  if (card.card_type !== "agent_identity") return null;
  return (
    <AgentIdentityCard
      agentId={draftAgentId}
      suggestedDisplayName={card.payload.display_name}
    />
  );
};

const renderFinalReview: StructuredCardRenderer = (card, draftAgentId) => {
  if (card.card_type !== "final_review") return null;
  return (
    <FinalizeCard
      data={{
        ...(card.payload as FinalReviewCardPayload),
        agent_id: draftAgentId,
      }}
    />
  );
};

export const nl2AgentCardRegistry: Record<
  StructuredNl2AgentCardType,
  StructuredCardRenderer
> = {
  requirements_summary: renderRequirementsSummary,
  model_selection: renderModelSelection,
  local_resources: renderLocalResources,
  web_mcp: renderWebMcp,
  web_skill: renderWebSkill,
  agent_identity: renderAgentIdentity,
  final_review: renderFinalReview,
};

export const renderStructuredNl2AgentCard = (
  card: StructuredNl2AgentCard,
  draftAgentId: number
): React.ReactNode => nl2AgentCardRegistry[card.card_type](card, draftAgentId);

export const renderStructuredNl2AgentEnvelope = (
  envelope: StructuredNl2AgentCardEnvelope
): React.ReactNode[] =>
  (envelope.cards ?? []).map((card) => (
    <React.Fragment key={`${card.card_type}:${card.card_key}`}>
      {renderStructuredNl2AgentCard(card, envelope.draft_agent_id)}
    </React.Fragment>
  ));
