// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import type { KnowledgeBase } from "@/types/knowledgeBase";
import type {
  ResourceItemSlots,
  ResourceViewMode,
} from "@/types/resourcePicker";
import type { KnowledgeItem } from "./types";
import type { TagAssignmentValue } from "@/types/tagManagement";
import { ResourceCollection, ResourceItem } from "./ResourceItem";
import { ResourceAssignedTags } from "./ResourceAssignedTags";

export function toKnowledgeItem(
  kb: KnowledgeBase,
  t: TFunction,
  options?: { isAidp?: boolean; groupNames?: string[] }
): KnowledgeItem {
  const isAidp = options?.isAidp ?? false;
  const description = kb.description?.trim() ?? "";
  const displayDescription = /^elasticsearch index$/i.test(description)
    ? ""
    : description;
  const meta: string[] = [
    `${t("knowledgeBase.create.field.embeddingModel")}: ${
      kb.embeddingModel && kb.embeddingModel !== "unknown"
        ? kb.embeddingModel
        : t("common.unknown")
    }`,
  ];

  if (isAidp) {
    meta.push(
      t("resourcePicker.knowledge.documents", { count: kb.documentCount })
    );
    meta.push(t("resourcePicker.knowledge.chunks", { count: kb.chunkCount }));
    options?.groupNames?.forEach((name) => meta.push(name));
    return {
      id: kb.id,
      name: kb.display_name || kb.name,
      category:
        kb.ingroup_permission === "PRIVATE"
          ? t("resourcePicker.knowledge.private")
          : options?.groupNames?.[0],
      description: displayDescription,
      meta,
    };
  }

  meta.push(
    t("resourcePicker.knowledge.documents", { count: kb.documentCount })
  );
  meta.push(t("resourcePicker.knowledge.chunks", { count: kb.chunkCount }));
  return {
    id: kb.id,
    name: kb.display_name || kb.name,
    category: kb.source || undefined,
    description: displayDescription,
    meta,
  };
}

/** Knowledge presentation shared by configuration and conversation controllers. */
export function KnowledgeSelectionList({
  knowledgeBases,
  selection,
  viewMode = "list",
  slots,
  isAidpSearch = false,
  groupNamesFor = () => [],
  assignments,
  refreshKey,
}: {
  knowledgeBases: KnowledgeBase[];
  selection: {
    ids: ReadonlySet<string>;
    toggle: (id: string) => void;
    canSelect?: (kb: KnowledgeBase) => boolean;
    disabledReason?: (kb: KnowledgeBase) => string | undefined;
  };
  viewMode?: ResourceViewMode;
  slots?: ResourceItemSlots<KnowledgeBase>;
  isAidpSearch?: boolean;
  groupNamesFor?: (kb: KnowledgeBase) => string[];
  assignments?: Record<string, TagAssignmentValue[]>;
  refreshKey?: number;
}) {
  const { t } = useTranslation("common");
  return (
    <ResourceCollection
      viewMode={viewMode}
      className={viewMode === "list" ? "gap-0" : undefined}
    >
      {knowledgeBases.map((kb) => {
        const item = toKnowledgeItem(kb, t, {
          isAidp: isAidpSearch,
          groupNames: groupNamesFor(kb),
        });
        return (
          <ResourceItem
            key={kb.id}
            item={{
              key: kb.id,
              name: item.name,
              description: [item.description, ...item.meta]
                .filter(Boolean)
                .join(" · "),
              badges: [
                ...(isAidpSearch && item.category ? [item.category] : []),
                ...(kb.is_multimodal === true
                  ? [t("resourcePicker.knowledge.multimodal", "多模态")]
                  : kb.is_multimodal === false
                    ? [t("resourcePicker.knowledge.textOnly", "仅文本")]
                    : []),
              ],
              tags: kb.tags,
              raw: kb,
            }}
            viewMode={viewMode}
            slots={{
              ...slots,
              renderDescription:
                slots?.renderDescription ??
                (() => (
                  <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
                    {[item.description, ...item.meta]
                      .filter(Boolean)
                      .map((text, index) => (
                        <span key={index}>{text}</span>
                      ))}
                  </span>
                )),
              renderTags:
                slots?.renderTags ??
                (() => (
                  <ResourceAssignedTags
                    resourceType="knowledge_base"
                    resourceId={kb.id}
                    tags={kb.tags}
                    assignments={assignments?.[kb.id] ?? []}
                    refreshKey={refreshKey}
                  />
                )),
              renderTitleTrailing:
                slots?.renderTitleTrailing ??
                (() => (
                  <span
                    className="truncate rounded-full border border-border bg-muted px-2 text-xs leading-5 text-muted-foreground"
                    title={kb.source || t("common.unknown")}
                  >
                    {kb.source || t("common.unknown")}
                  </span>
                )),
              renderMetadata: slots?.renderMetadata ?? (() => null),
            }}
            selected={selection.ids.has(kb.id)}
            disabled={selection.canSelect ? !selection.canSelect(kb) : false}
            disabledReason={selection.disabledReason?.(kb)}
            onToggle={() => selection.toggle(kb.id)}
          />
        );
      })}
    </ResourceCollection>
  );
}
