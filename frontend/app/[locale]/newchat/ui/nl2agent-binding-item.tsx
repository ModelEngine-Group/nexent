// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import {
  BookOpen,
  CheckCircle2,
  HardDrive,
  Loader2,
  Plug,
  Settings2,
  Sparkles,
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

interface BindingResourceItemProps {
  item: BindingItemState;
  tool?: Tool;
  ui: {
    locked: boolean;
    binding: boolean;
    catalogFetching: boolean;
    catalogError: boolean;
    configLoading: boolean;
    configuring: boolean;
  };
  onToggle: () => void;
  onConfigure: () => void;
  onCloseConfig: () => void;
  onSaveKnowledge: (params: Nl2AgentResourceParam[]) => void;
}

export function Nl2AgentBindingItem({
  item,
  tool,
  ui,
  onToggle,
  onConfigure,
  onCloseConfig,
  onSaveKnowledge,
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
  const CategoryIcon =
    category === "Skill" ? Sparkles : category === "MCP" ? Plug : HardDrive;
  const categoryStyle =
    category === "Skill"
      ? "border-emerald-200 bg-emerald-50 text-emerald-600"
      : category === "MCP"
        ? "border-blue-200 bg-blue-50 text-blue-600"
        : "border-gray-200 bg-gray-100 text-gray-500";
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
      {!bound ? (
        <input
          type="checkbox"
          checked={item.selected}
          disabled={disabled}
          onChange={onToggle}
          className="mt-1 size-4 shrink-0 cursor-pointer rounded accent-blue-600"
          aria-label={displayName}
        />
      ) : null}
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-start justify-between gap-2">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <span
              className={`break-words text-xs text-foreground ${bound ? "font-normal" : "font-semibold"}`}
            >
              {displayName}
            </span>
            <span
              className={`inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[10px] leading-none ${categoryStyle}`}
            >
              <CategoryIcon className="size-3" aria-hidden="true" />
              {category}
            </span>
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
            {knowledgeName || item.draftParams.length ? (
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
                  disabled ||
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
        {knowledgeName && !bound ? (
          <p className="mt-2 line-clamp-2 text-xs leading-5 text-muted-foreground">
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
            disabled={disabled || unavailable}
            hideTrigger
            compact={bound}
            onOpen={onConfigure}
            onClose={onCloseConfig}
            onChange={onSaveKnowledge}
          />
        ) : !bound ? (
          <p
            className="mt-2 line-clamp-2 break-words text-xs leading-5 text-muted-foreground"
            title={candidate.description}
          >
            {candidate.description}
          </p>
        ) : null}
        <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
          <span className="inline-flex items-center gap-1">
            <Target className="size-3" aria-hidden="true" />
            {t("nl2agent.resourceBinding.matches", "Matches")}
          </span>
          {candidate.requirement_ids.map((id) => (
            <span
              key={id}
              className="max-w-full break-all rounded bg-muted px-1.5 py-0.5 text-[10px] leading-none text-foreground"
            >
              {id}
            </span>
          ))}
        </div>
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
