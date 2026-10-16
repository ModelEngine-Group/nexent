// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Database } from "lucide-react";
import { Empty, Spin } from "antd";
import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";
import { useEmbeddingModelDialog } from "@/hooks/knowledge/useEmbeddingModelDialog";
import { KnowledgeModelMismatchModal } from "@/components/tool-config/KnowledgeModelMismatchModal";

import { cn } from "@/lib/utils";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useKnowledgeList } from "@/hooks/knowledge/useKnowledgeList";
import { useGroupList } from "@/hooks/group/useGroupList";
import { formatDate } from "@/lib/date";
import type { KnowledgeBase } from "@/types/knowledgeBase";
import knowledgeBaseService from "@/services/knowledgeBaseService";
import log from "@/lib/logger";
import EmbeddingModelConfigDialog from "@/components/tool-config/EmbeddingModelConfigDialog";
import {
  getKnowledgeBaseEmbeddingIdentity,
  isEmbeddingModelCompatible as isEmbeddingModelCompatibleBase,
  isMultimodalConstraintMismatch as isMultimodalConstraintMismatchBase,
} from "@/lib/knowledgeBaseCompatibility";
import { AddResourceDrawer, CheckMark } from "./AddResourceDrawer";
import type { KnowledgeItem, SelectedItem } from "./types";
import styles from "./ResourcePickerDrawer.module.css";

const PAGE_SIZE = 10;

const ICON_BG_PALETTE = [
  "#8B7BF6",
  "#7B5BF2",
  "#9F8CF8",
  "#5B8DEF",
  "#3B82F6",
  "#4D6BFE",
];

function iconColorFor(seed: string): string {
  let hash = 0;
  for (let i = 0; i < seed.length; i += 1) {
    hash = (hash * 31 + seed.charCodeAt(i)) >>> 0;
  }
  return ICON_BG_PALETTE[hash % ICON_BG_PALETTE.length];
}

function toKnowledgeItem(
  kb: KnowledgeBase,
  t: TFunction,
  options?: { isAidp?: boolean; groupNames?: string[] }
): KnowledgeItem {
  const isAidp = options?.isAidp ?? false;
  const meta: string[] = [];

  if (isAidp) {
    const created = formatDate(kb.createdAt);
    if (created) meta.push(created);
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
      description: kb.description ?? "",
      iconBg: iconColorFor(kb.id),
      meta,
    };
  }

  const usedAt = formatDate(kb.updatedAt);
  if (usedAt) meta.push(t("resourcePicker.knowledge.usedAt", { date: usedAt }));
  meta.push(
    t("resourcePicker.knowledge.documents", { count: kb.documentCount })
  );
  meta.push(t("resourcePicker.knowledge.chunks", { count: kb.chunkCount }));
  return {
    id: kb.id,
    name: kb.display_name || kb.name,
    category: kb.source || undefined,
    description: kb.description ?? "",
    iconBg: iconColorFor(kb.id),
    meta,
  };
}

function KnowledgeRow({
  item,
  selected,
  onToggle,
  canSelect = true,
}: {
  item: KnowledgeItem;
  selected: boolean;
  onToggle: () => void;
  canSelect?: boolean;
}) {
  return (
    <div
      data-knowledge-selected={selected}
      className={cn(
        "relative flex h-[104px] w-full shrink-0 flex-col items-start justify-between",
        !canSelect ? "opacity-60" : ""
      )}
    >
      <div className="flex h-8 w-full shrink-0 items-center gap-2 pr-10">
        <div
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-white"
          style={{
            background: "linear-gradient(135deg, #B8A3FF 0%, #6941D9 100%)",
          }}
        >
          <Database size={20} strokeWidth={1.8} />
        </div>
        <div className="flex min-w-0 items-center gap-2">
          <span
            className="min-w-0 truncate text-[14px] font-bold leading-[21px] text-[#191919]"
            style={{
              fontFamily: '"HarmonyHeiTi", "HarmonyOS Sans SC", sans-serif',
            }}
          >
            {item.name}
          </span>
          {item.category && (
            <span
              className="flex h-5 shrink-0 items-center rounded-[2px] border border-[#D9D9D9] bg-[#F2F2F2] px-[6px] text-[12px] leading-[18px] text-[#4D4D4D]"
              style={{
                fontFamily: '"HarmonyHeiTi", "HarmonyOS Sans SC", sans-serif',
              }}
            >
              {item.category}
            </span>
          )}
        </div>
      </div>
      <p
        className="line-clamp-2 h-9 w-[calc(100%-40px)] text-[12px] leading-[18px] text-[#191919]/70"
        style={{
          fontFamily: '"HarmonyHeiTi", "HarmonyOS Sans SC", sans-serif',
        }}
      >
        {item.description}
      </p>
      <div
        className="flex h-[18px] w-[calc(100%-40px)] items-center text-[12px] leading-[18px] text-[#191919]/40"
        style={{
          fontFamily: '"HarmonyHeiTi", "HarmonyOS Sans SC", sans-serif',
        }}
      >
        {item.meta.map((text, i) => (
          <span key={text} className="flex items-center">
            {i > 0 && <span className="mx-4 h-2.5 w-px bg-[#DDD]" />}
            {text}
          </span>
        ))}
      </div>
      <div className="absolute right-0 top-1/2 -translate-y-1/2">
        <CheckMark
          checked={selected}
          onToggle={canSelect ? onToggle : undefined}
        />
      </div>
    </div>
  );
}

export interface AddKnowledgeDrawerProps {
  open: boolean;
  onClose: () => void;
  onConfirm?: (selected: KnowledgeBase[]) => void;
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
  // Embedding-model compatibility inputs for nexent-source validation.
  toolMultimodal?: boolean | null;
  currentEmbeddingModel?: string | null;
  currentMultiEmbeddingModel?: string | null;
  currentEmbeddingModelId?: number | null;
  currentMultiEmbeddingModelId?: number | null;
}

export function AddKnowledgeDrawer({
  open,
  onClose,
  onConfirm,
  title,
  knowledgeBases: knowledgeBasesProp,
  isLoading: isLoadingProp,
  selectedIds: selectedIdsProp = [],
  maxSelect,
  isAidpSearch = false,
  onRefresh,
  toolMultimodal = null,
  currentEmbeddingModel = null,
  currentMultiEmbeddingModel = null,
  currentEmbeddingModelId = null,
  currentMultiEmbeddingModelId = null,
}: AddKnowledgeDrawerProps) {
  const { t } = useTranslation("common");
  const { user } = useAuthorizationContext();
  const tenantId = user?.tenantId ?? null;

  // Self-fetching fallback (used by the standalone demo page).
  const selfFetch = useKnowledgeList(tenantId);
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
  const isLoading = controlled ? (isLoadingProp ?? false) : selfFetch.isLoading;

  const groupNamesFor = (kb: KnowledgeBase): string[] =>
    (kb.group_ids ?? [])
      .map((groupId) => groupNameById.get(groupId))
      .filter((name): name is string => Boolean(name));

  const allItems: KnowledgeItem[] = useMemo(
    () =>
      knowledgeBases.map((kb) =>
        toKnowledgeItem(kb, t, {
          isAidp: isAidpSearch,
          groupNames: groupNamesFor(kb),
        })
      ),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [knowledgeBases, isAidpSearch, groupNameById, t]
  );

  // ---- Selection state (seeded from props on open) ----
  const [selectedIdsSet, setSelectedIdsSet] = useState<Set<string>>(
    () => new Set()
  );
  const [keyword, setKeyword] = useState("");
  const [page, setPage] = useState(1);
  const [tagFilter, setTagFilter] = useState("");

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
      setKeyword("");
      setTagFilter("");
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

  // ---- Selection validation (parity with KnowledgeBaseSelectorModal) ----
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

    onConfirm?.(selectedKBs);
    onClose();
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
  ]);

  // ---- Filters / pagination ----
  const tagOptions = useMemo(() => {
    if (isAidpSearch) return [];
    const sources = new Set<string>();
    allItems.forEach((item) => {
      if (item.category) sources.add(item.category);
    });
    return Array.from(sources)
      .sort((left, right) => (left < right ? -1 : Number(left > right)))
      .map((value) => ({ value, label: value }));
  }, [allItems, isAidpSearch]);

  const filteredKbs = useMemo(() => {
    let filtered = knowledgeBases;
    const kw = keyword.trim().toLowerCase();
    if (kw) {
      filtered = filtered.filter(
        (kb) =>
          kb.name.toLowerCase().includes(kw) ||
          (kb.description ?? "").toLowerCase().includes(kw)
      );
    }
    if (tagFilter) {
      filtered = filtered.filter((kb) => kb.source === tagFilter);
    }
    return filtered;
  }, [knowledgeBases, keyword, tagFilter]);

  useEffect(() => {
    setPage(1);
  }, [keyword, tagFilter]);

  const pagedItems = useMemo(
    () =>
      filteredKbs.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE).map((kb) =>
        toKnowledgeItem(kb, t, {
          isAidp: isAidpSearch,
          groupNames: groupNamesFor(kb),
        })
      ),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [filteredKbs, page, isAidpSearch, groupNameById, t]
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
    else void selfFetch.refetch();
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
      <AddResourceDrawer
        width={768}
        bodyClassName={cn(styles.drawer, styles.knowledge)}
        open={open}
        title={title ?? t("resourcePicker.addKnowledge", "添加知识库")}
        searchPlaceholder={t(
          "resourcePicker.search.knowledge",
          "搜索知识库名称及描述"
        )}
        selected={selected}
        tagOptions={tagOptions}
        listTitle={t("resourcePicker.list.knowledge", "知识库列表")}
        total={filteredKbs.length}
        page={page}
        onPageChange={setPage}
        showConfirm
        onClose={onClose}
        onConfirm={() => {
          void handleConfirm();
        }}
        onRemoveSelected={(id) => toggleSelection(id)}
        onSearch={setKeyword}
        onTagChange={(value) => setTagFilter(value ?? "")}
        onRefresh={handleRefresh}
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
          <div className="flex flex-col gap-0">
            {pagedItems.map((item) => {
              const kb = filteredKbs.find((k) => k.id === item.id);
              const selected_ = selectedIdsSet.has(item.id);
              const canSelect = kb ? checkCanSelect(kb) : true;
              return (
                <div
                  key={item.id}
                  data-knowledge-row
                  className={cn(
                    "box-border flex h-32 w-full shrink-0 items-center px-4 py-3 shadow-[inset_0_-1px_0_#fff]",
                    selected_ ? "bg-[#E6F2FD]" : "bg-white"
                  )}
                >
                  <KnowledgeRow
                    item={item}
                    selected={selected_}
                    canSelect={canSelect}
                    onToggle={() => kb && toggleSelection(kb.id)}
                  />
                </div>
              );
            })}
          </div>
        )}
      </AddResourceDrawer>

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
