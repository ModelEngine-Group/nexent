// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { Empty, Spin } from "antd";
import { Sparkles } from "lucide-react";
import { useTranslation } from "react-i18next";
import Image from "next/image";

import { cn } from "@/lib/utils";
import { MODEL_PROVIDER_LOGOS } from "@/const/modelConfig";
import { useModelList } from "@/hooks/model/useModelList";
import type { ModelOption } from "@/types/modelConfig";
import { AddResourceDrawer, CheckMark } from "./AddResourceDrawer";
import type { ModelGroup, ModelItem, SelectedItem } from "./types";

const PAGE_SIZE = 10;

const ICON_BG_PALETTE = ["#4D6BFE", "#7B5BF2", "#2E5BFF", "#3B82F6", "#1F2329"];

function iconColorFor(seed: string): string {
  let hash = 0;
  for (let i = 0; i < seed.length; i += 1) {
    hash = (hash * 31 + seed.charCodeAt(i)) >>> 0;
  }
  return ICON_BG_PALETTE[hash % ICON_BG_PALETTE.length];
}

function toModelItem(model: ModelOption, capabilityTags: string[]): ModelItem {
  const tags: string[] = [];
  const contextTokens = model.contextWindowTokens ?? model.maxInputTokens;
  if (contextTokens && contextTokens > 0) {
    tags.push(`${Math.round(contextTokens / 1000)}k`);
  }
  tags.push(...capabilityTags);
  return {
    id: String(model.id),
    name: model.displayName || model.name,
    tags,
    provider: String(model.modelFactory || model.source || "").toLowerCase(),
  };
}

export interface AddModelDrawerProps {
  open: boolean;
  onClose: () => void;
  onConfirm?: (selected: ModelItem[]) => void;
  models?: ModelOption[];
  selectedModelIds?: readonly number[];
  onSelectionChange?: (modelIds: number[]) => void;
  disabled?: boolean;
  selectedTrailing?: ReactNode;
}

export function AddModelDrawer({
  open,
  onClose,
  onConfirm,
  models,
  selectedModelIds,
  onSelectionChange,
  disabled = false,
  selectedTrailing,
}: AddModelDrawerProps) {
  const { t } = useTranslation("common");
  const {
    llmModels: queriedModels,
    isLoading: queryLoading,
    refetch,
  } = useModelList({ enabled: open && !models });
  const llmModels = models ?? queriedModels;
  const isLoading = !models && queryLoading;

  const [activeGroup, setActiveGroup] = useState("");
  // Draft selection edited locally inside the drawer. Changes are only committed
  // to the parent when the confirm button is clicked.
  const [draftIds, setDraftIds] = useState<number[]>([]);
  useEffect(() => {
    if (!open) return;
    setDraftIds(selectedModelIds ? [...selectedModelIds] : []);
  }, [open, selectedModelIds]);
  const draftIdSet = useMemo(() => new Set(draftIds.map(String)), [draftIds]);
  const [keyword, setKeyword] = useState("");
  const [page, setPage] = useState(1);

  // Base helper: source key for a model (falls back for models without one).
  const sourceOf = (model: ModelOption) => model.source || "unknown";

  // Capability tags mirror the outer selected-model card so the drawer list and
  // the agent's model list present the same labels.
  const capabilityTagsFor = useCallback(
    (model: ModelOption): string[] => {
      const tags: string[] = [];
      if (model.type === "llm") {
        tags.push(t("agent.highFidelity.modelCapability.text"));
      }
      if (model.reasoningCapability?.status === "supported") {
        tags.push(t("agent.highFidelity.modelCapability.reasoning"));
      }
      if (model.supportToolCalls === true) {
        tags.push(t("agent.highFidelity.modelCapability.tools"));
      }
      return tags;
    },
    [t]
  );

  // Group the account's own LLM models by their source in first-seen order.
  const groups: ModelGroup[] = useMemo(() => {
    const sources: string[] = [];
    llmModels.forEach((model) => {
      const source = sourceOf(model);
      if (!sources.includes(source)) sources.push(source);
    });
    return sources.map((source) => ({
      key: source,
      label: source,
      icon: source.charAt(0).toUpperCase(),
      iconBg: iconColorFor(source),
    }));
  }, [llmModels]);

  // Default to the first available source group.
  useEffect(() => {
    if (
      groups.length > 0 &&
      !groups.some((group) => group.key === activeGroup)
    ) {
      setActiveGroup(groups[0].key);
    }
  }, [groups, activeGroup]);

  const allModels = useMemo(
    () => llmModels.map((model) => toModelItem(model, capabilityTagsFor(model))),
    [llmModels, capabilityTagsFor]
  );

  const activeModels = useMemo(() => {
    const list = llmModels
      .filter((model) => !activeGroup || sourceOf(model) === activeGroup)
      .map((model) => toModelItem(model, capabilityTagsFor(model)));
    const kw = keyword.trim().toLowerCase();
    if (!kw) return list;
    return list.filter(
      (item) =>
        item.name.toLowerCase().includes(kw) ||
        item.tags.some((tag) => tag.toLowerCase().includes(kw))
    );
  }, [llmModels, activeGroup, keyword, capabilityTagsFor]);

  // Reset to the first page whenever the source group or search changes.
  useEffect(() => {
    setPage(1);
  }, [keyword, activeGroup]);

  const pagedModels = activeModels.slice(
    (page - 1) * PAGE_SIZE,
    page * PAGE_SIZE
  );

  const selected: SelectedItem[] = useMemo(
    () =>
      draftIds.flatMap((id) => {
        const item = allModels.find((model) => model.id === String(id));
        return item ? [{ id: item.id, label: item.name }] : [];
      }),
    [allModels, draftIds]
  );

  const toggleModel = (id: string) => {
    if (disabled) return;
    const modelId = Number(id);
    setDraftIds((prev) =>
      prev.includes(modelId)
        ? prev.filter((value) => value !== modelId)
        : [...prev, modelId]
    );
  };

  const handleConfirm = () => {
    if (selectedModelIds !== undefined) {
      onSelectionChange?.(draftIds);
    } else {
      onConfirm?.(
        allModels.filter((model) => draftIds.includes(Number(model.id)))
      );
    }
    onClose();
  };

  return (
    <AddResourceDrawer
      open={open}
      title={t("resourcePicker.addModel", "添加模型")}
      searchPlaceholder={t("resourcePicker.search.model", "按名称、描述检索")}
      selected={selected}
      selectedTrailing={selectedTrailing}
      listTitle={t("resourcePicker.list.model", "模型列表")}
      total={activeModels.length}
      page={page}
      onPageChange={setPage}
      onClose={onClose}
      onConfirm={handleConfirm}
      onRemoveSelected={(id) => toggleModel(id)}
      onSearch={setKeyword}
      onRefresh={() => {
        void refetch();
      }}
    >
      {isLoading ? (
        <div className="flex justify-center py-12">
          <Spin />
        </div>
      ) : (
        <div className="flex h-full gap-4">
          <div className="flex w-[216px] shrink-0 flex-col gap-1">
            {groups.map((group) => (
              <button
                key={group.key}
                type="button"
                onClick={() => setActiveGroup(group.key)}
                className={cn(
                  "flex h-11 cursor-pointer items-center gap-2 rounded-[2px] border-0 bg-transparent px-3 text-left text-[14px] leading-[22px]",
                  activeGroup === group.key
                    ? "bg-[#E6F2FD] text-[#0067D1]"
                    : "text-[#191919]"
                )}
              >
                <span
                  className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-[9px] text-white"
                  style={{ background: group.iconBg }}
                >
                  {group.icon}
                </span>
                {group.label}
                <span className="ml-auto text-[12px] text-[#B3B3B3]">›</span>
              </button>
            ))}
          </div>
          <div className="flex min-w-0 flex-1 flex-col gap-2 overflow-y-auto pl-2">
            {pagedModels.length === 0 ? (
              <Empty description={t("resourcePicker.empty", "暂无数据")} />
            ) : (
              pagedModels.map((item) => {
                const isSelected = draftIdSet.has(item.id);
                const providerLogo =
                  MODEL_PROVIDER_LOGOS[item.provider ?? ""];
                return (
                  <div
                    key={item.id}
                    className={cn(
                      "flex h-[59px] shrink-0 items-center justify-between rounded-[2px] py-[9px] pl-5 pr-7",
                      isSelected ? "bg-[#E6F2FD]" : "bg-white"
                    )}
                  >
                    <div className="flex items-center gap-3">
                      <span className="flex size-5 shrink-0 items-center justify-center overflow-hidden">
                        {providerLogo ? (
                          <Image
                            src={providerLogo}
                            alt=""
                            aria-hidden="true"
                            width={20}
                            height={20}
                            className="size-5 object-contain"
                          />
                        ) : (
                          <Sparkles
                            size={17}
                            className="text-[#2673e5]"
                            aria-hidden="true"
                          />
                        )}
                      </span>
                      <div className="flex min-w-0 flex-col gap-0.5">
                        <span
                          className={cn(
                            "truncate text-[14px] leading-[22px]",
                            isSelected
                              ? "font-medium text-[#0067D1]"
                              : "font-medium text-[#191919]"
                          )}
                        >
                          {item.name}
                        </span>
                        <div className="flex gap-2">
                          {item.tags.map((tag) => (
                            <span
                              key={tag}
                              className="h-5 rounded-[2px] bg-[#F5F5F5] px-2 text-[12px] leading-[20px] text-[#393939]"
                            >
                              {tag}
                            </span>
                          ))}
                        </div>
                      </div>
                    </div>
                    <CheckMark
                      checked={isSelected}
                      ariaLabel={item.name}
                      onToggle={() => toggleModel(item.id)}
                    />
                  </div>
                );
              })
            )}
          </div>
        </div>
      )}
    </AddResourceDrawer>
  );
}
