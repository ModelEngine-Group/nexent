// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useState } from "react";
import { BookOpen, Check, Sparkles } from "lucide-react";
import type { Nl2aKnowledgeRecommendation } from "../adapter/remote-chat-model-adapter";
import { useTranslation } from "react-i18next";
import { KnowledgeDrawer } from "@/components/resource-picker/KnowledgeDrawer";
import { StandardButton } from "@/components/common/StandardButton";
import { useKnowledgeBasesForToolConfig } from "@/hooks/useKnowledgeBaseSelector";
import type { ManagedKnowledgeToolName } from "@/lib/managedKnowledgeTools";
import type { Nl2AgentResourceParam } from "./nl2agent-resource-config";
import {
  knowledgeSelectionIds,
  withKnowledgeSelection,
} from "./nl2agent-knowledge-config";

export function Nl2AgentKnowledgePicker({
  toolName,
  suggestions = [],
  associatedValues = [],
  params,
  open,
  disabled,
  onOpen,
  onClose,
  onChange,
  hideTrigger = false,
  compact = false,
}: {
  toolName: ManagedKnowledgeToolName;
  suggestions?: Nl2aKnowledgeRecommendation[];
  associatedValues?: string[];
  params: Nl2AgentResourceParam[];
  open: boolean;
  disabled: boolean;
  onOpen: () => void;
  onClose: () => void;
  onChange: (params: Nl2AgentResourceParam[]) => void;
  hideTrigger?: boolean;
  compact?: boolean;
}) {
  const { t } = useTranslation("common");
  const [userConfirmedSelection, setUserConfirmedSelection] = useState(false);
  const {
    data: knowledgeBases = [],
    isLoading,
    isError,
    refetch,
  } = useKnowledgeBasesForToolConfig(toolName);
  const aidp = toolName === "aidp_search";
  const ids = knowledgeSelectionIds(params, toolName);
  const selected = knowledgeBases.filter((kb) =>
    ids.includes(aidp ? String(kb.id) : String(kb.index_name || kb.id))
  );
  const displayIds =
    compact || userConfirmedSelection
      ? ids
      : ids.filter((id) => !associatedValues.includes(id));
  const selectedNames = displayIds.map((id) => {
    const kb = selected.find(
      (item) =>
        (aidp ? String(item.id) : String(item.index_name || item.id)) === id
    );
    return (
      kb?.display_name ||
      kb?.name ||
      suggestions.find((suggestion) => suggestion.binding_value === id)?.name ||
      t(
        "nl2agent.resourceBinding.knowledgeUnavailable",
        "Unavailable knowledge base"
      )
    );
  });

  return (
    <div className={compact ? "mt-1 space-y-1" : "mt-2 space-y-2"}>
      <div
        className="flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground"
        aria-live="polite"
      >
        <span className="inline-flex items-center gap-1">
          <BookOpen className="size-3" aria-hidden="true" />
          {compact
            ? t(
                "nl2agent.resourceBinding.associatedKnowledge",
                "Associated knowledge bases:"
              )
            : userConfirmedSelection
              ? t(
                  "nl2agent.resourceBinding.selectedKnowledge",
                  "Selected knowledge bases:"
                )
              : t(
                  "nl2agent.resourceBinding.recommendedKnowledge",
                  "Recommended knowledge bases:"
                )}
        </span>
        {selectedNames.length ? (
          selectedNames.map((name, index) => (
            <span
              key={displayIds[index]}
              className="inline-flex max-w-full items-center gap-1 rounded border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-[10px] leading-4 text-foreground"
            >
              {userConfirmedSelection && !compact ? (
                <Check
                  className="size-3 shrink-0 text-amber-600"
                  aria-hidden="true"
                />
              ) : (
                <Sparkles
                  className="size-3 shrink-0 text-amber-600"
                  aria-hidden="true"
                />
              )}
              <span className="break-words">{name}</span>
            </span>
          ))
        ) : (
          <span>
            {isLoading
              ? t(
                  "nl2agent.resourceBinding.knowledgeLoading",
                  "Loading knowledge bases..."
                )
              : t("nl2agent.resourceBinding.knowledgeNone", "None")}
          </span>
        )}
      </div>
      {isError ? (
        <div role="alert" className="text-xs text-destructive">
          {t(
            "nl2agent.resourceBinding.knowledgeLoadFailed",
            "Failed to load knowledge bases."
          )}
          <StandardButton disabled={disabled} onClick={() => void refetch()}>
            {t("nl2agent.resourceBinding.retry", "Retry failed")}
          </StandardButton>
        </div>
      ) : null}
      {!hideTrigger ? (
        <StandardButton
          disabled={disabled || isLoading || isError}
          onClick={onOpen}
        >
          {t(
            "nl2agent.resourceBinding.selectKnowledge",
            "Select knowledge bases"
          )}
        </StandardButton>
      ) : null}
      {open && !disabled ? (
        <KnowledgeDrawer
          open
          onClose={onClose}
          onConfirm={(selection) => {
            setUserConfirmedSelection(true);
            onChange(withKnowledgeSelection(params, toolName, selection));
            onClose();
          }}
          selectedIds={selected.map((kb) => String(kb.id))}
          knowledgeBases={knowledgeBases}
          isLoading={isLoading || isError}
          isAidpSearch={aidp}
          maxSelect={aidp ? 10 : undefined}
          toolMultimodal={
            params.find((param) => param.name === "multimodal")?.value ?? null
          }
          onRefresh={() => void refetch()}
        />
      ) : null}
    </div>
  );
}
