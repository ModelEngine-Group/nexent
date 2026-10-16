// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Alert, Empty, Spin } from "antd";
import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";
import { useEmbeddingModelDialog } from "@/hooks/knowledge/useEmbeddingModelDialog";
import { KnowledgeModelMismatchModal } from "@/components/tool-config/KnowledgeModelMismatchModal";

import { cn } from "@/lib/utils";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useKnowledgeList } from "@/hooks/knowledge/useKnowledgeList";
import { useGroupList } from "@/hooks/group/useGroupList";
import type { KnowledgeBase } from "@/types/knowledgeBase";
import knowledgeBaseService from "@/services/knowledgeBaseService";
import log from "@/lib/logger";
import EmbeddingModelConfigDialog from "@/components/tool-config/EmbeddingModelConfigDialog";
import {
  getKnowledgeBaseEmbeddingIdentity,
  isEmbeddingModelCompatible as isEmbeddingModelCompatibleBase,
  isMultimodalConstraintMismatch as isMultimodalConstraintMismatchBase,
} from "@/lib/knowledgeBaseCompatibility";
import { ResourceDrawer } from "./ResourceDrawer";
import { ResourceCollection, ResourceItem } from "./ResourceItem";
import type {
  ResourceItemSlots,
  ResourceViewMode,
} from "@/types/resourcePicker";
import type { KnowledgeItem, SelectedItem } from "./types";
import { useResourceTagFilter } from "@/hooks/useResourceTagFilter";
import { ResourceTagFilterControl } from "./ResourceTagFilterControl";
import { ResourceAssignedTags } from "./ResourceAssignedTags";
import { ResourceTagManagementModal } from "./ResourceTagManagementModal";

import styles from "./ResourcePickerDrawer.module.css";

function toKnowledgeItem(
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

export interface KnowledgeDrawerProps {
  open: boolean;
  onClose: () => void;
  onConfirm?: (selected: KnowledgeBase[]) => void | Promise<void>;
  viewMode?: ResourceViewMode;
  slots?: ResourceItemSlots<KnowledgeBase>;
  /** Drawer title; falls back to the localized "添加知识库". */
  title?: string;
  /** When provided, the drawer is controlled and uses this list instead of self-fetching. */
  knowledgeBases?: KnowledgeBase[];
  isLoading?: boolean;
  /** Pre-selected knowledge base ids. */
  selectedIds?: string[];
  maxSelect?: number;
  isAidpSearch?: boolean;
  /** Refresh action (wired to the drawer's refresh button). */
  onRefresh?: () => void;
  onOpenManageTags?: () => void;
  enableTagManagement?: boolean;
  // Embedding-model compatibility inputs for nexent-source validation.
  toolMultimodal?: boolean | null;
  currentEmbeddingModel?: string | null;
  currentMultiEmbeddingModel?: string | null;
  currentEmbeddingModelId?: number | null;
  currentMultiEmbeddingModelId?: number | null;
}

export function KnowledgeDrawer({
  open,
  onClose,
  onConfirm,
  viewMode = "list",
  slots,
  title,
  knowledgeBases: knowledgeBasesProp,
  isLoading: isLoadingProp,
  selectedIds: selectedIdsProp = [],
  maxSelect,
  isAidpSearch = false,
  onRefresh,
  onOpenManageTags,
  enableTagManagement = false,
  toolMultimodal = null,
  currentEmbeddingModel = null,
  currentMultiEmbeddingModel = null,
  currentEmbeddingModelId = null,
  currentMultiEmbeddingModelId = null,
}: KnowledgeDrawerProps) {
  const { t } = useTranslation("common");
  const [tagManagementOpen, setTagManagementOpen] = useState(false);
  const [previousOpen, setPreviousOpen] = useState(open);
  if (previousOpen !== open) {
    setPreviousOpen(open);
    if (!open) setTagManagementOpen(false);
  }
  const { user } = useAuthorizationContext();
  const tenantId = user?.tenantId ?? null;

  // Self-fetching fallback (used by the standalone demo page).
  const selfFetch = useKnowledgeList(
    open && knowledgeBasesProp === undefined ? tenantId : null
  );
  const { data: groupListData } = useGroupList(isAidpSearch ? tenantId : null);

  const groupNameById = useMemo(
    () =>
      new Map(
        (groupListData?.groups ?? []).map((group) => [
          group.group_id,
          group.group_name,
        ])
      ),
    [groupListData]
  );

  const controlled = knowledgeBasesProp !== undefined;
  const knowledgeBases = knowledgeBasesProp ?? selfFetch.data ?? [];
  const resourceTags = useResourceTagFilter(
    open,
    "knowledge_base",
    knowledgeBases.map((kb) => kb.id)
  );
  const isLoading = controlled ? (isLoadingProp ?? false) : selfFetch.isLoading;

  const groupNamesFor = (kb: KnowledgeBase): string[] =>
    (kb.group_ids ?? [])
      .map((groupId) => groupNameById.get(groupId))
      .filter((name): name is string => Boolean(name));

  // ---- Selection state (seeded from props on open) ----
  const [selectedIdsSet, setSelectedIdsSet] = useState<Set<string>>(
    () => new Set()
  );
  const confirming = useRef(false);
  const [saving, setSaving] = useState(false);
  const [confirmError, setConfirmError] = useState<string>();
  const [keyword, setKeyword] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);

  // Model-mismatch confirm modal state.
  const [pendingSelection, setPendingSelection] = useState<{
    id: string;
    kb: KnowledgeBase;
  } | null>(null);
  const [confirmModalOpen, setConfirmModalOpen] = useState(false);
  const [modelMismatchInfo, setModelMismatchInfo] = useState<{
    existingModel: string;
    newModel: string;
    existingKBName: string;
    newKBName: string;
  } | null>(null);

  // Embedding model config dialog state.
  const {
    setEmbeddingModelDialogOpen,
    setEmbeddingModelDialogData,
    setEmbeddingModelDialogMismatch,
    setConfiguringKbIds,
    embeddingModelDialogProps,
  } = useEmbeddingModelDialog();
  const [configuredKbIndexNames, setConfiguredKbIndexNames] = useState<
    Set<string>
  >(new Set());

  useEffect(() => {
    if (open) {
      setSelectedIdsSet(new Set(selectedIdsProp ?? []));
      setConfirmError(undefined);
      setKeyword("");
      setPage(1);
      setEmbeddingModelDialogOpen(false);
      setEmbeddingModelDialogData(null);
      setEmbeddingModelDialogMismatch(false);
      setConfiguredKbIndexNames(new Set());
      setConfiguringKbIds(new Set());
      setConfirmModalOpen(false);
      setPendingSelection(null);
      setModelMismatchInfo(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // ---- Selection validation (parity with KnowledgeSelectorDrawer) ----
  const checkCanSelect = useCallback(
    (kb: KnowledgeBase): boolean => {
      if (isAidpSearch) return true;

      const isEmpty =
        (kb.documentCount || 0) === 0 && (kb.chunkCount || 0) === 0;
      if (isEmpty) return false;

      if (kb.source === "nexent") {
        if (isMultimodalConstraintMismatchBase(kb, toolMultimodal)) {
          return false;
        }
        return isEmbeddingModelCompatibleBase(
          kb,
          currentEmbeddingModel,
          currentMultiEmbeddingModel,
          currentEmbeddingModelId,
          currentMultiEmbeddingModelId
        );
      }

      return true;
    },
    [
      isAidpSearch,
      toolMultimodal,
      currentEmbeddingModel,
      currentMultiEmbeddingModel,
      currentEmbeddingModelId,
      currentMultiEmbeddingModelId,
    ]
  );

  const toggleSelection = useCallback(
    (id: string) => {
      const kb = knowledgeBases.find((k) => k.id === id);
      if (!kb || !checkCanSelect(kb)) return;

      setSelectedIdsSet((prev) => {
        if (prev.has(id)) {
          const next = new Set(prev);
          next.delete(id);
          return next;
        }

        if (maxSelect && prev.size >= maxSelect) {
          return prev;
        }

        const newIdentity = getKnowledgeBaseEmbeddingIdentity(kb);
        if (kb.source === "nexent" && newIdentity) {
          const existingNexentIdentities = new Set(
            knowledgeBases
              .filter((k) => prev.has(k.id) && k.source === "nexent")
              .map(getKnowledgeBaseEmbeddingIdentity)
              .filter((identity): identity is string => identity !== null)
          );
          if (
            existingNexentIdentities.size > 0 &&
            !existingNexentIdentities.has(newIdentity)
          ) {
            const existingKB = knowledgeBases.find(
              (k) => prev.has(k.id) && k.source === "nexent"
            );
            setModelMismatchInfo({
              existingModel: existingKB?.embeddingModel || "unknown",
              newModel: kb.embeddingModel,
              existingKBName: existingKB?.name || "",
              newKBName: kb.name,
            });
            setPendingSelection({ id, kb });
            setConfirmModalOpen(true);
            return prev;
          }
        }

        const next = new Set(prev);
        next.add(id);
        return next;
      });
    },
    [knowledgeBases, maxSelect, checkCanSelect]
  );

  const clearAllSelections = useCallback(() => {
    setSelectedIdsSet(new Set());
  }, []);

  const handleEmbeddingModelConfigComplete = useCallback(
    (indexNames: string, _modelId: string, _modelDisplayName?: string) => {
      const indexNameList = indexNames.split(",").filter(Boolean);
      setConfiguredKbIndexNames((prev) => {
        const next = new Set(prev);
        indexNameList.forEach((name) => next.add(name.trim()));
        return next;
      });
      setEmbeddingModelDialogOpen(false);
      setEmbeddingModelDialogData(null);
      setEmbeddingModelDialogMismatch(false);
      setConfiguringKbIds(new Set());
    },
    [
      setConfiguringKbIds,
      setEmbeddingModelDialogData,
      setEmbeddingModelDialogMismatch,
      setEmbeddingModelDialogOpen,
    ]
  );

  const handleConfirm = useCallback(async () => {
    const selectedKBs = knowledgeBases.filter((kb) =>
      selectedIdsSet.has(kb.id)
    );
    const nexentKBs = selectedKBs.filter((kb) => kb.source === "nexent");
    const nexentModelIds = [
      ...new Set(
        nexentKBs
          .map(getKnowledgeBaseEmbeddingIdentity)
          .filter((identity): identity is string => identity !== null)
      ),
    ];

    if (nexentModelIds.length > 1) {
      const firstKB = nexentKBs[0];
      setEmbeddingModelDialogData({
        indexName: firstKB.index_name || firstKB.name,
        knowledgeName: `${nexentKBs.length} knowledge bases`,
      });
      setEmbeddingModelDialogMismatch(true);
      setEmbeddingModelDialogOpen(true);
      setConfiguringKbIds(
        new Set(nexentKBs.map((k) => k.index_name || k.name))
      );
      return;
    }

    const kbIdsNeedingConfig: string[] = [];
    const kbNamesNeedingConfig: string[] = [];

    for (const kb of selectedKBs) {
      if (kb.source !== "nexent") continue;
      const kbIndexName = kb.index_name || kb.name;
      if (configuredKbIndexNames.has(kbIndexName)) continue;

      try {
        const status =
          await knowledgeBaseService.getEmbeddingModelStatus(kbIndexName);
        if (status.needs_config) {
          kbIdsNeedingConfig.push(kbIndexName);
          kbNamesNeedingConfig.push(kb.name);
        }
      } catch (error) {
        log.error("Failed to check embedding model status:", error);
        if (!kb.embeddingModel || kb.embeddingModel === "unknown") {
          kbIdsNeedingConfig.push(kbIndexName);
          kbNamesNeedingConfig.push(kb.name);
        }
      }
    }

    if (kbIdsNeedingConfig.length > 0) {
      setEmbeddingModelDialogData({
        indexName: kbIdsNeedingConfig[0],
        knowledgeName:
          kbIdsNeedingConfig.length === 1
            ? kbNamesNeedingConfig[0]
            : `${kbIdsNeedingConfig.length} knowledge bases`,
      });
      setEmbeddingModelDialogMismatch(false);
      setEmbeddingModelDialogOpen(true);
      setConfiguringKbIds(new Set(kbIdsNeedingConfig));
      return;
    }

    if (confirming.current) return;
    confirming.current = true;
    setSaving(true);
    setConfirmError(undefined);
    try {
      await onConfirm?.(selectedKBs);
      onClose();
    } catch (error) {
      setConfirmError(
        error instanceof Error
          ? error.message
          : t("resourcePicker.selectionFailed", "选择失败，请重试")
      );
    } finally {
      confirming.current = false;
      setSaving(false);
    }
  }, [
    knowledgeBases,
    onConfirm,
    onClose,
    selectedIdsSet,
    setEmbeddingModelDialogData,
    setEmbeddingModelDialogMismatch,
    setEmbeddingModelDialogOpen,
    setConfiguringKbIds,
    configuredKbIndexNames,
    t,
  ]);

  // ---- Filters / pagination ----
  const filteredKbs = useMemo(() => {
    let filtered = knowledgeBases.filter(
      (kb) => !resourceTags.matchedIds || resourceTags.matchedIds.has(kb.id)
    );
    const kw = keyword.trim().toLowerCase();
    if (kw) {
      filtered = filtered.filter(
        (kb) =>
          kb.name.toLowerCase().includes(kw) ||
          (kb.description ?? "").toLowerCase().includes(kw)
      );
    }
    return filtered;
  }, [knowledgeBases, keyword, resourceTags.matchedIds]);

  useEffect(() => {
    setPage(1);
  }, [keyword, resourceTags.matchedIds]);

  const pagedItems = useMemo(
    () =>
      filteredKbs.slice((page - 1) * pageSize, page * pageSize).map((kb) =>
        toKnowledgeItem(kb, t, {
          isAidp: isAidpSearch,
          groupNames: groupNamesFor(kb),
        })
      ),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [filteredKbs, page, pageSize, isAidpSearch, groupNameById, t]
  );

  const selected: SelectedItem[] = useMemo(
    () =>
      knowledgeBases
        .filter((kb) => selectedIdsSet.has(kb.id))
        .map((kb) => ({ id: kb.id, label: kb.display_name || kb.name })),
    [knowledgeBases, selectedIdsSet]
  );

  const allSelected =
    filteredKbs.length > 0 &&
    filteredKbs.every((kb) => selectedIdsSet.has(kb.id));

  const handleRefresh = () => {
    if (onRefresh) onRefresh();
    else if (!controlled) void selfFetch.refetch();
  };

  const handleSelectAll = (checked: boolean) => {
    if (!checked) {
      clearAllSelections();
      return;
    }
    const remaining = maxSelect ? maxSelect - selectedIdsSet.size : undefined;
    if (remaining !== undefined && remaining <= 0) return;
    const selectable = filteredKbs
      .filter((kb) => checkCanSelect(kb) && !selectedIdsSet.has(kb.id))
      .map((kb) => kb.id);
    const toAdd =
      remaining !== undefined ? selectable.slice(0, remaining) : selectable;
    setSelectedIdsSet((prev) => {
      const next = new Set(prev);
      toAdd.forEach((id) => next.add(id));
      return next;
    });
  };

  return (
    <>
      <ResourceDrawer
        width="min(768px, 100vw)"
        keyword={keyword}
        confirmLoading={saving}
        confirmDisabled={
          isLoading ||
          resourceTags.filtering ||
          !!(resourceTags.predicates.length && resourceTags.error)
        }
        controlsContent={
          confirmError ? <Alert type="error" title={confirmError} /> : undefined
        }
        bodyClassName={cn(styles.drawer, styles.knowledge)}
        open={open}
        title={title ?? t("resourcePicker.addKnowledge", "添加知识库")}
        searchPlaceholder={t(
          "resourcePicker.search.knowledge",
          "搜索知识库名称及描述"
        )}
        selected={selected}
        tagFilter={
          <ResourceTagFilterControl
            filter={resourceTags}
            onChange={() => setPage(1)}
          />
        }
        listTitle={t("resourcePicker.list.knowledge", "知识库列表")}
        tagManagement={
          onOpenManageTags || enableTagManagement
            ? {
                onClick: onOpenManageTags ?? (() => setTagManagementOpen(true)),
              }
            : undefined
        }
        total={filteredKbs.length}
        page={page}
        onPageChange={setPage}
        pageSize={pageSize}
        onPageSizeChange={(size) => {
          setPageSize(size);
          setPage(1);
        }}
        showConfirm
        onClose={onClose}
        onConfirm={() => {
          void handleConfirm();
        }}
        onRemoveSelected={(id) => toggleSelection(id)}
        onSearch={setKeyword}
        onRefresh={onRefresh || !controlled ? handleRefresh : undefined}
        onSelectAll={handleSelectAll}
        allSelected={allSelected}
      >
        {isLoading ? (
          <div className="flex justify-center py-12">
            <Spin />
          </div>
        ) : filteredKbs.length === 0 ? (
          <Empty description={t("resourcePicker.empty", "暂无数据")} />
        ) : (
          <ResourceCollection
            viewMode={viewMode}
            className={viewMode === "list" ? "gap-0" : undefined}
          >
            {pagedItems.map((item) => {
              const kb = filteredKbs.find((k) => k.id === item.id);
              const selected_ = selectedIdsSet.has(item.id);
              const canSelect = kb ? checkCanSelect(kb) : true;
              if (kb) {
                return (
                  <ResourceItem
                    key={item.id}
                    item={{
                      key: item.id,
                      name: item.name,
                      description: [item.description, ...item.meta]
                        .filter(Boolean)
                        .join(" · "),
                      badges: [
                        ...(isAidpSearch && item.category
                          ? [item.category]
                          : []),
                        ...(kb.is_multimodal === true
                          ? [t("resourcePicker.knowledge.multimodal", "多模态")]
                          : kb.is_multimodal === false
                            ? [t("resourcePicker.knowledge.textOnly", "仅文本")]
                            : []),
                      ],
                      tags: kb.tags,
                      metadata: item.meta.map((value, index) => ({
                        key: String(index),
                        value,
                        label: "",
                      })),
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
                            refreshKey={resourceTags.revision}
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
                    selected={selected_}
                    disabled={!canSelect}
                    onToggle={() => toggleSelection(kb.id)}
                  />
                );
              }
              return null;
            })}
          </ResourceCollection>
        )}
      </ResourceDrawer>

      {tagManagementOpen && (
        <ResourceTagManagementModal
          resourceType="knowledge_base"
          resources={knowledgeBases.map((kb) => ({
            id: kb.id,
            name: kb.display_name || kb.name,
            canEdit: kb.permission === "EDIT",
          }))}
          definitions={resourceTags.definitions}
          onClose={() => {
            setTagManagementOpen(false);
            resourceTags.retry();
          }}
          onSaved={() => resourceTags.retry()}
        />
      )}

      {/* Model-mismatch confirmation modal */}
      <KnowledgeModelMismatchModal
        open={confirmModalOpen}
        info={modelMismatchInfo}
        onCancel={() => {
          setConfirmModalOpen(false);
          setPendingSelection(null);
          setModelMismatchInfo(null);
        }}
        onConfirm={() => {
          if (pendingSelection) {
            setSelectedIdsSet(new Set([pendingSelection.id]));
          }
          setConfirmModalOpen(false);
          setPendingSelection(null);
          setModelMismatchInfo(null);
        }}
      />

      {/* Embedding model config dialog */}
      <EmbeddingModelConfigDialog
        {...embeddingModelDialogProps}
        onConfigComplete={handleEmbeddingModelConfigComplete}
      />
    </>
  );
}
