// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import {
  BookOpen,
  CheckCircle2,
  Loader2,
  Settings2,
  Target,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import type { Tool } from "@/types/agentConfig";
import { useKnowledgeBasesForToolConfig } from "@/hooks/useKnowledgeBaseSelector";
import type { BindingItemState } from "./installed-resource-binding-card";
import type { Nl2AgentResourceParam } from "./nl2agent-resource-config";
import { knowledgeToolName } from "./nl2agent-knowledge-config";
import { Nl2AgentKnowledgePicker } from "./nl2agent-knowledge-picker";
import { Nl2AgentResourceKindBadge } from "./nl2agent-resource-kind-badge";

interface BindingResourceItemProps {
  item: BindingItemState;
  matchScore?: number;
  tool?: Tool;
  matchedRequirements: string[];
  ui: {
    locked: boolean;
    configurationLocked: boolean;
    binding: boolean;
    catalogFetching: boolean;
    catalogError: boolean;
    configLoading: boolean;
    configuring: boolean;
    knowledgeLoading?: boolean;
    knowledgeError?: boolean;
  };
  onToggle: () => void;
  onConfigure: () => void;
  onCloseConfig: () => void;
  onSaveKnowledge: (params: Nl2AgentResourceParam[]) => void;
  onRetryKnowledge?: () => void;
}

export function Nl2AgentBindingItem({
  item,
  matchScore,
  tool,
  matchedRequirements,
  ui,
  onToggle,
  onConfigure,
  onCloseConfig,
  onSaveKnowledge,
  onRetryKnowledge,
}: BindingResourceItemProps) {
  const { t } = useTranslation("common");
  const candidate = item.resource.candidate;
  const knowledgeName = knowledgeToolName(candidate, tool);
  const knowledgeCatalog = useKnowledgeBasesForToolConfig(knowledgeName);
  const bound = item.bindingStatus === "bound";
  const isTool = candidate.resource_type === "tool";
  const unavailable = isTool && !tool;
  const loading = unavailable && ui.catalogFetching;
  const disabled = ui.locked || ui.binding;
  const displayName =
    knowledgeName &&
    ["knowledge_base_search", "aidp_search"].includes(candidate.name)
      ? t("nl2agent.resourceBinding.knowledgeTitle", "Knowledge search")
      : candidate.name;
  const category = !isTool
    ? "Skill"
    : candidate.source === "MCP_TOOL"
      ? "MCP"
      : "Local";
  const configureTitle = loading
    ? t("toolPool.loadingTools", "Loading tools...")
    : isTool && ui.catalogError
      ? t(
          "agentConfig.tools.fetchFailed",
          "Failed to fetch tools list, please try again later"
        )
      : unavailable
        ? t("toolPool.tooltip.unavailableTool", "Tool is unavailable")
        : t("nl2agent.resourceBinding.configure", "Configure");

  return (
    <div
      data-resource-ref={candidate.candidate_ref}
      className={`flex min-w-0 items-start gap-3 px-4 ${bound ? "py-3" : "py-4"} ${!bound && item.selected ? "bg-blue-50/60" : ""}`}
    >
      <input
        type="checkbox"
        checked={bound || item.selected}
        disabled={bound || disabled}
        onChange={onToggle}
        className={`mt-1 size-4 shrink-0 rounded ${bound ? "cursor-not-allowed accent-[var(--color-text-disabled)]" : "cursor-pointer accent-blue-600"}`}
        aria-label={displayName}
      />
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-start justify-between gap-2">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <span
              title={candidate.candidate_ref}
              className={`break-words text-[13px] text-foreground ${bound ? "font-normal" : "font-semibold"}`}
            >
              {displayName}
            </span>
            <Nl2AgentResourceKindBadge kind={category} />
            {knowledgeName ? (
              <span className="inline-flex items-center gap-1 rounded-md border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-[10px] leading-none text-amber-600">
                <BookOpen className="size-3" aria-hidden="true" />
                Knowledge
              </span>
            ) : null}
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {bound ? (
              <span className="inline-flex items-center gap-1 whitespace-nowrap text-xs text-emerald-600">
                <CheckCircle2 className="size-3.5" />
                {t("nl2agent.resourceBinding.bound", "Bound")}
              </span>
            ) : null}
            {knowledgeName ||
            item.resource.has_config ||
            item.draftParams.length ? (
              <Button
                type="button"
                variant={bound ? "ghost" : "outline"}
                size={bound ? "icon" : "sm"}
                title={configureTitle}
                aria-label={
                  knowledgeName
                    ? t(
                        "nl2agent.resourceBinding.selectKnowledge",
                        "Select knowledge bases"
                      )
                    : `${configureTitle} ${displayName}`
                }
                disabled={
                  (bound && item.resource.readiness !== undefined) ||
                  disabled ||
                  Boolean(
                    ui.knowledgeLoading &&
                    !item.knowledgeEdited &&
                    !item.knowledgePreparation
                  ) ||
                  unavailable ||
                  Boolean(
                    knowledgeName &&
                    (knowledgeCatalog.isLoading || knowledgeCatalog.isError)
                  )
                }
                onClick={onConfigure}
                className={
                  bound
                    ? "size-6 text-muted-foreground"
                    : `h-7 gap-1 rounded-md bg-white px-2 text-xs shadow-none ${item.configStatus === "invalid" ? "border-destructive" : ""}`
                }
              >
                {loading || ui.configLoading ? (
                  <Loader2 className="size-3.5 animate-spin" />
                ) : (
                  <Settings2 className="size-3.5" />
                )}
                {!bound
                  ? t("nl2agent.resourceBinding.configure", "Configure")
                  : null}
              </Button>
            ) : null}
          </div>
        </div>
        {typeof matchScore === "number" && Number.isFinite(matchScore) ? (
          <span className="text-xs text-muted-foreground">
            {t("nl2agent.coverage.relevanceScore", "Relevance score")}:{" "}
            <span className="text-[var(--color-success)]">
              {Math.round(matchScore * 100)}
            </span>
          </span>
        ) : null}
        {knowledgeName && !bound ? (
          <p className="mt-1 line-clamp-2 text-xs leading-5 text-muted-foreground">
            {t(
              "nl2agent.resourceBinding.knowledgeDescription",
              "Search selected knowledge bases for relevant information and supporting references."
            )}
          </p>
        ) : null}
        {knowledgeName ? (
          <Nl2AgentKnowledgePicker
            toolName={knowledgeName}
            suggestions={item.resource.knowledge_recommendations}
            associatedValues={item.resource.knowledge_bound_values}
            params={item.draftParams}
            open={ui.configuring}
            disabled={ui.configurationLocked || ui.binding || unavailable}
            hideTrigger
            compact={bound}
            preparation={item.knowledgePreparation}
            userEdited={item.knowledgeEdited}
            recommendationLoading={ui.knowledgeLoading}
            recommendationError={ui.knowledgeError}
            onRetryRecommendation={onRetryKnowledge}
            onOpen={onConfigure}
            onClose={onCloseConfig}
            onChange={onSaveKnowledge}
          />
        ) : !bound ? (
          <p
            className="mt-1 line-clamp-2 break-words text-xs leading-5 text-muted-foreground"
            title={candidate.description}
          >
            {candidate.description}
          </p>
        ) : null}
        {matchedRequirements.length > 0 ? (
          <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
            <span className="inline-flex items-center gap-1">
              <Target className="size-3" aria-hidden="true" />
              {t("nl2agent.resourceBinding.matches", "Matches")}
            </span>
            {matchedRequirements.map((query) => (
              <span
                key={query}
                className="max-w-full break-words rounded bg-muted px-1.5 py-0.5 text-[10px] text-foreground"
              >
                {query}
              </span>
            ))}
          </div>
        ) : null}
        {item.fieldErrors.length ? (
          <p role="alert" className="mt-2 text-xs text-destructive">
            {knowledgeName
              ? t(
                  "nl2agent.resourceBinding.knowledgeRequired",
                  "Select at least one knowledge base (up to 10 for AIDP)."
                )
              : item.fieldErrors.map((error) => error.field).join(", ")}
          </p>
        ) : item.error ? (
          <p role="alert" className="mt-2 text-xs text-destructive">
            {item.error.message}
          </p>
        ) : null}
        {item.bindingStatus === "failed" ? (
          <p className="mt-1 text-xs text-destructive">
            {t("nl2agent.resourceBinding.failed", "Failed")}
          </p>
        ) : null}
      </div>
    </div>
  );
}
