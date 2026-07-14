"use client";

import React, { useEffect } from "react";
import { message } from "antd";
import { resolveNl2AgentCardAgentId } from "@/lib/chat/nl2agentDraftContext";
import { LocalResourcesCard, LocalResourceItem } from "./LocalResourcesCard";
import { WebMcpCard, WebMcpCardItem } from "./WebMcpCard";
import { WebSkillCard, WebSkillCardItem } from "./WebSkillCard";
import { FinalizeCard } from "./FinalizeCard";
import { ModelSelectionCard } from "./ModelSelectionCard";
import { AgentIdentityCard } from "./AgentIdentityCard";
import { registerOnlineResourceRecommendations } from "@/services/nl2agentService";
import { useNl2AgentWorkflow } from "./Nl2AgentWorkflowContext";

export const OnlineRecommendationGroup: React.FC<{
  agentId: number;
  recommendationBatchId: string;
  resourceType: "mcp" | "skill";
  itemKeys: string[];
  children: React.ReactNode;
}> = ({ agentId, recommendationBatchId, resourceType, itemKeys, children }) => {
  const workflow = useNl2AgentWorkflow();
  const serializedKeys = JSON.stringify(itemKeys);

  useEffect(() => {
    if (!recommendationBatchId || !workflow.active) return;
    workflow.beginAction();
    void registerOnlineResourceRecommendations(agentId, {
      recommendation_batch_id: recommendationBatchId,
      resource_type: resourceType,
      item_keys: itemKeys,
    })
      .then(() => workflow.notifyStateChanged())
      .catch((error) =>
        message.error(
          error instanceof Error
            ? error.message
            : "Failed to register online recommendations."
        )
      )
      .finally(() => workflow.endAction());
    // Stable serialized keys prevent repeated registration from array identity changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    agentId,
    recommendationBatchId,
    resourceType,
    serializedKeys,
    workflow.active,
  ]);

  return <>{children}</>;
};

/**
 * Registry that maps fenced-code-block language tags to NL2AGENT card
 * renderers. The NL2AGENT LLM emits JSON inside these fenced blocks in its
 * final answer; markdownRenderer.tsx routes matching blocks here.
 *
 * Supported tags:
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
  /** Optional handler to open the existing AddMcpServiceModal prefilled. */
  onInstallMcp?: (item: WebMcpCardItem) => void;
  trustedDraftAgentId?: number | null;
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
  onInstallMcp?: (item: WebMcpCardItem) => void,
  trustedDraftAgentId?: number | null
): React.ReactNode | null => {
  const normalizedLanguage = language?.trim().toLowerCase();
  if (!normalizedLanguage || !normalizedLanguage.startsWith("nl2agent-")) {
    return null;
  }
  if (normalizedLanguage.startsWith("nl2agent-search-")) {
    return renderInvalidSearchCard();
  }

  let parsed: any;
  try {
    parsed = JSON.parse(content);
  } catch {
    return (
      <div className="my-2 p-3 border border-red-200 rounded bg-red-50 text-xs text-red-700">
        Invalid NL2AGENT card JSON: {content.slice(0, 120)}
      </div>
    );
  }

  const { agentId, mismatch } = resolveNl2AgentCardAgentId(
    parsed.agent_id,
    Array.isArray(parsed.items)
      ? parsed.items.map((item: any) => item?.agent_id)
      : [],
    trustedDraftAgentId
  );
  if (mismatch) {
    return renderMismatchedAgentId();
  }
  if (agentId == null) {
    return renderInvalidAgentId();
  }

  switch (normalizedLanguage) {
    case "nl2agent-model-selection":
      return <ModelSelectionCard agentId={agentId} />;
    case "nl2agent-agent-identity":
      return (
        <AgentIdentityCard
          agentId={agentId}
          suggestedDisplayName={
            typeof parsed.display_name === "string"
              ? parsed.display_name
              : undefined
          }
        />
      );
    case "nl2agent-local-resources": {
      const tools: LocalResourceItem[] = (parsed.tools || []).map((x: any) => ({
        ...x,
        kind: "tool" as const,
      }));
      const skills: LocalResourceItem[] = (parsed.skills || []).map(
        (x: any) => ({
          ...x,
          kind: "skill" as const,
        })
      );
      return (
        <LocalResourcesCard
          agentId={agentId}
          recommendationBatchId={String(parsed.recommendation_batch_id || "")}
          tools={tools}
          skills={skills}
        />
      );
    }
    case "nl2agent-web-mcp": {
      if (!parsed.recommendation_batch_id) return renderMissingOnlineBatch();
      const item: WebMcpCardItem = parsed;
      return (
        <OnlineRecommendationGroup
          agentId={agentId}
          recommendationBatchId={String(parsed.recommendation_batch_id || "")}
          resourceType="mcp"
          itemKeys={[String(item.recommendation_id || "")].filter(Boolean)}
        >
          <WebMcpCard agentId={agentId} item={item} onInstall={onInstallMcp} />
        </OnlineRecommendationGroup>
      );
    }
    case "nl2agent-web-mcps": {
      if (!parsed.recommendation_batch_id) return renderMissingOnlineBatch();
      const items: WebMcpCardItem[] = parsed.items || [];
      return (
        <OnlineRecommendationGroup
          agentId={agentId}
          recommendationBatchId={String(parsed.recommendation_batch_id || "")}
          resourceType="mcp"
          itemKeys={items
            .map((item) => String(item.recommendation_id || ""))
            .filter(Boolean)}
        >
          {items.map((item, i) => (
            <WebMcpCard
              key={i}
              agentId={agentId}
              item={item}
              onInstall={onInstallMcp}
            />
          ))}
        </OnlineRecommendationGroup>
      );
    }
    case "nl2agent-web-skill": {
      if (!parsed.recommendation_batch_id) return renderMissingOnlineBatch();
      const item: WebSkillCardItem = parsed;
      const itemKey = item.skill_id
        ? `skill:${item.skill_id}`
        : `skill-name:${String(item.skill_name || item.name || "")
            .trim()
            .toLowerCase()}`;
      return (
        <OnlineRecommendationGroup
          agentId={agentId}
          recommendationBatchId={String(parsed.recommendation_batch_id || "")}
          resourceType="skill"
          itemKeys={[itemKey]}
        >
          <WebSkillCard agentId={agentId} item={item} />
        </OnlineRecommendationGroup>
      );
    }
    case "nl2agent-web-skills": {
      if (!parsed.recommendation_batch_id) return renderMissingOnlineBatch();
      const items: WebSkillCardItem[] = parsed.items || [];
      return (
        <OnlineRecommendationGroup
          agentId={agentId}
          recommendationBatchId={String(parsed.recommendation_batch_id || "")}
          resourceType="skill"
          itemKeys={items.map((item) =>
            item.skill_id
              ? `skill:${item.skill_id}`
              : `skill-name:${String(item.skill_name || item.name || "")
                  .trim()
                  .toLowerCase()}`
          )}
        >
          {items.map((item, i) => (
            <WebSkillCard key={i} agentId={agentId} item={item} />
          ))}
        </OnlineRecommendationGroup>
      );
    }
    case "nl2agent-finalize": {
      // Forward the full agent spec to FinalizeCard so it can display
      // all fields and call the finalize endpoint on "Publish".
      const { agent_id, ...rest } = parsed;
      return <FinalizeCard data={{ agent_id: agentId, ...rest } as any} />;
    }
    default:
      return null;
  }
};
