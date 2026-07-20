"use client";

import React, { useCallback, useEffect, useState } from "react";
import { Alert, Button } from "antd";
import { LocalResourcesCard } from "./LocalResourcesCard";
import { WebMcpCard } from "./WebMcpCard";
import { WebSkillCard } from "./WebSkillCard";
import { FinalizeCard } from "./FinalizeCard";
import { ModelSelectionCard } from "./ModelSelectionCard";
import { AgentIdentityCard } from "./AgentIdentityCard";
import { RequirementsSummaryCard } from "./RequirementsSummaryCard";
import {
  isNl2AgentWorkflowConflict,
  registerOnlineResourceRecommendations,
} from "@/services/nl2agentService";
import { useNl2AgentWorkflow } from "./Nl2AgentWorkflowContext";
import { useNl2AgentCardLifecycle } from "./useNl2AgentCardLifecycle";
import {
  parseNl2AgentCard,
  type Nl2AgentCardRegistrationHandler,
  type ValidatedNl2AgentCard,
} from "./cardValidation";
import {
  toWebSkillCardItem,
  webSkillRecommendationKey,
} from "./cardPayloadTypes";

export const OnlineRecommendationGroup: React.FC<{
  agentId: number;
  recommendationBatchId: string;
  resourceType: "mcp" | "skill";
  itemKeys: string[];
  children: React.ReactNode;
  onRegistered?: Nl2AgentCardRegistrationHandler;
  registrationEnabled?: boolean;
}> = ({
  agentId,
  recommendationBatchId,
  resourceType,
  itemKeys,
  children,
  onRegistered,
  registrationEnabled = true,
}) => {
  const workflow = useNl2AgentWorkflow();
  const { notifyStateChanged } = workflow;
  const { execute, error } = useNl2AgentCardLifecycle(
    `online:${agentId}:${resourceType}:${recommendationBatchId}`
  );
  const serializedKeys = JSON.stringify(itemKeys);
  const [registered, setRegistered] = useState(false);
  const [completed, setCompleted] = useState(false);
  const [registrationRetryable, setRegistrationRetryable] = useState(true);

  useEffect(() => {
    const batch =
      workflow.sessionState?.resource_review.online_recommendation_batches?.[
        recommendationBatchId
      ];
    if (!batch || batch.resource_type !== resourceType) return;
    setCompleted(batch.status === "completed");
    if (!registrationEnabled) setRegistered(true);
  }, [
    recommendationBatchId,
    registrationEnabled,
    resourceType,
    workflow.sessionState,
  ]);

  const register = useCallback(async () => {
    if (
      registered ||
      !recommendationBatchId ||
      !workflow.active ||
      !registrationEnabled
    )
      return;
    setRegistrationRetryable(true);
    try {
      await execute(
        () =>
          registerOnlineResourceRecommendations(agentId, {
            recommendation_batch_id: recommendationBatchId,
            resource_type: resourceType,
            item_keys: JSON.parse(serializedKeys),
          }),
        {
          onSuccess: async (result) => {
            setCompleted(result.status === "completed");
            await onRegistered?.({
              cardType: resourceType === "mcp" ? "web_mcp" : "web_skill",
              cardKey: recommendationBatchId,
            });
            setRegistered(true);
          },
          notifyStateChanged: true,
          blockInput: true,
          retainInputBlockOnError: (error) =>
            !isNl2AgentWorkflowConflict(error),
        }
      );
    } catch (error) {
      const retryable = !isNl2AgentWorkflowConflict(error);
      setRegistrationRetryable(retryable);
      if (!retryable) notifyStateChanged();
    }
  }, [
    agentId,
    execute,
    onRegistered,
    notifyStateChanged,
    recommendationBatchId,
    resourceType,
    serializedKeys,
    workflow.active,
    registrationEnabled,
    registered,
  ]);

  useEffect(() => {
    void register();
  }, [register]);

  return (
    <div>
      {error && (
        <Alert
          className="my-2"
          type="error"
          message={error}
          action={
            registrationRetryable ? (
              <Button size="small" onClick={() => void register()}>
                Retry registration
              </Button>
            ) : undefined
          }
        />
      )}
      {!error && workflow.active && workflow.sessionStateError && (
        <Alert
          className="my-2"
          type="error"
          message="Failed to restore online resource state."
          action={
            <Button
              size="small"
              onClick={() => void workflow.refreshSessionState()}
            >
              Retry
            </Button>
          }
        />
      )}
      <div
        className={
          !registered || completed ? "pointer-events-none opacity-60" : ""
        }
      >
        {children}
      </div>
    </div>
  );
};

/**
 * Registry that maps fenced-code-block language tags to NL2AGENT card
 * renderers. The NL2AGENT LLM emits JSON inside these fenced blocks in its
 * final answer; markdownRenderer.tsx routes matching blocks here.
 *
 * Supported tags:
 *   ```nl2agent-requirements-summary -> RequirementsSummaryCard
 *   ```nl2agent-model-selection      -> ModelSelectionCard
 *   ```nl2agent-agent-identity       -> AgentIdentityCard
 *   ```nl2agent-local-resources  -> LocalResourcesCard
 *   ```nl2agent-web-mcp          -> WebMcpCard (single)
 *   ```nl2agent-web-mcps         -> list of WebMcpCard
 *   ```nl2agent-web-skill        -> WebSkillCard (single)
 *   ```nl2agent-web-skills       -> list of WebSkillCard
 *   ```nl2agent-finalize         -> FinalizeCard
 */

export interface Nl2AgentCardRendererProps {
  language: string;
  content: string;
  trustedDraftAgentId?: number | null;
  onRegistered?: Nl2AgentCardRegistrationHandler;
  registrationEnabled?: boolean;
}

const renderInvalidAgentId = () => (
  <div className="my-2 p-3 border border-red-200 rounded bg-red-50 text-xs text-red-700">
    Invalid NL2AGENT card JSON: missing draft agent_id.
  </div>
);

const renderMismatchedAgentId = () => (
  <div className="my-2 p-3 border border-red-200 rounded bg-red-50 text-xs text-red-700">
    Invalid NL2AGENT card JSON: draft agent_id does not match the active
    conversation.
  </div>
);

const renderInvalidSearchCard = () => (
  <div className="my-2 p-3 border border-red-200 rounded bg-red-50 text-xs text-red-700">
    Invalid NL2AGENT search card: search must be executed by the agent before a
    result card can be rendered.
  </div>
);

const renderMissingOnlineBatch = () => (
  <div className="my-2 rounded border border-red-200 bg-red-50 p-3 text-xs text-red-700">
    Invalid NL2AGENT online resource card: missing recommendation_batch_id.
  </div>
);

/**
 * Try to render an NL2AGENT card from a fenced code block. Returns null if
 * the language tag is not an NL2AGENT tag (so the caller falls back to the
 * default code block renderer).
 */
export const tryRenderNl2AgentCard = (
  language: string,
  content: string,
  trustedDraftAgentId?: number | null,
  onRegistered?: Nl2AgentCardRegistrationHandler,
  registrationEnabled = false
): React.ReactNode | null => {
  const normalizedLanguage = language?.trim().toLowerCase();
  if (!normalizedLanguage || !normalizedLanguage.startsWith("nl2agent-")) {
    return null;
  }
  if (normalizedLanguage.startsWith("nl2agent-search-")) {
    return renderInvalidSearchCard();
  }

  const validation = parseNl2AgentCard(
    normalizedLanguage,
    content,
    trustedDraftAgentId
  );
  if (validation.failure?.agentIdError === "mismatch") {
    return renderMismatchedAgentId();
  }
  if (validation.failure?.agentIdError === "missing") {
    return renderInvalidAgentId();
  }
  if (validation.failure?.reason === "invalid_json") {
    return (
      <div className="my-2 p-3 border border-red-200 rounded bg-red-50 text-xs text-red-700">
        Invalid NL2AGENT card JSON: {content.slice(0, 120)}
      </div>
    );
  }
  if (
    validation.failure?.reason === "invalid_schema" &&
    !validation.failure.cardKey &&
    [
      "nl2agent-web-mcp",
      "nl2agent-web-mcps",
      "nl2agent-web-skill",
      "nl2agent-web-skills",
    ].includes(normalizedLanguage)
  ) {
    return renderMissingOnlineBatch();
  }
  if (validation.failure) {
    return (
      <div className="my-2 rounded border border-red-200 bg-red-50 p-3 text-xs text-red-700">
        Invalid NL2AGENT card: {validation.failure.reason}.
      </div>
    );
  }
  const card = validation.cards[0];
  if (!card) return null;
  return renderValidatedNl2AgentCard(card, onRegistered, registrationEnabled);
};

/** Render an already parsed and schema-validated card AST node. */
export const renderValidatedNl2AgentCard = (
  card: ValidatedNl2AgentCard,
  onRegistered?: Nl2AgentCardRegistrationHandler,
  registrationEnabled = false
): React.ReactNode => {
  const agentId = card.agentId;

  switch (card.language) {
    case "nl2agent-requirements-summary":
      return (
        <RequirementsSummaryCard
          agentId={agentId}
          summary={card.payload}
          onRegistered={onRegistered}
          registrationEnabled={registrationEnabled}
        />
      );
    case "nl2agent-model-selection":
      return <ModelSelectionCard agentId={agentId} />;
    case "nl2agent-agent-identity":
      return (
        <AgentIdentityCard
          agentId={agentId}
          suggestedDisplayName={card.payload.display_name}
        />
      );
    case "nl2agent-local-resources": {
      const tools = card.payload.tools.map((item) => ({
        ...item,
        kind: "tool" as const,
      }));
      const skills = card.payload.skills.map((item) => ({
        ...item,
        kind: "skill" as const,
      }));
      return (
        <LocalResourcesCard
          agentId={agentId}
          recommendationBatchId={card.payload.recommendation_batch_id}
          tools={tools}
          skills={skills}
          onRegistered={onRegistered}
          registrationEnabled={registrationEnabled}
        />
      );
    }
    case "nl2agent-web-mcp": {
      const item = card.payload;
      return (
        <OnlineRecommendationGroup
          agentId={agentId}
          recommendationBatchId={item.recommendation_batch_id}
          resourceType="mcp"
          itemKeys={[item.recommendation_id]}
          onRegistered={onRegistered}
          registrationEnabled={registrationEnabled}
        >
          <WebMcpCard agentId={agentId} item={item} />
        </OnlineRecommendationGroup>
      );
    }
    case "nl2agent-web-mcps": {
      const { items, recommendation_batch_id: recommendationBatchId } =
        card.payload;
      return (
        <OnlineRecommendationGroup
          agentId={agentId}
          recommendationBatchId={recommendationBatchId}
          resourceType="mcp"
          itemKeys={items.map((item) => item.recommendation_id)}
          onRegistered={onRegistered}
          registrationEnabled={registrationEnabled}
        >
          {items.map((item) => (
            <WebMcpCard
              key={item.recommendation_id}
              agentId={agentId}
              item={item}
            />
          ))}
        </OnlineRecommendationGroup>
      );
    }
    case "nl2agent-web-skill": {
      const item = toWebSkillCardItem(card.payload);
      return (
        <OnlineRecommendationGroup
          agentId={agentId}
          recommendationBatchId={card.payload.recommendation_batch_id}
          resourceType="skill"
          itemKeys={[webSkillRecommendationKey(item)]}
          onRegistered={onRegistered}
          registrationEnabled={registrationEnabled}
        >
          <WebSkillCard agentId={agentId} item={item} />
        </OnlineRecommendationGroup>
      );
    }
    case "nl2agent-web-skills": {
      const items = card.payload.items.map(toWebSkillCardItem);
      return (
        <OnlineRecommendationGroup
          agentId={agentId}
          recommendationBatchId={card.payload.recommendation_batch_id}
          resourceType="skill"
          itemKeys={items.map(webSkillRecommendationKey)}
          onRegistered={onRegistered}
          registrationEnabled={registrationEnabled}
        >
          {items.map((item) => (
            <WebSkillCard
              key={webSkillRecommendationKey(item)}
              agentId={agentId}
              item={item}
            />
          ))}
        </OnlineRecommendationGroup>
      );
    }
    case "nl2agent-finalize": {
      return <FinalizeCard data={{ ...card.payload, agent_id: agentId }} />;
    }
    default:
      return null;
  }
};
