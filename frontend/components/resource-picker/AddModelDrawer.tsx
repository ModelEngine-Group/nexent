"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Cpu } from "lucide-react";
import { Empty, Spin } from "antd";
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";
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

function toModelItem(model: ModelOption): ModelItem {
  const tags: string[] = [];
  if (model.contextWindowTokens) {
    tags.push(`${Math.round(model.contextWindowTokens / 1000)}k`);
  }
  if (model.source) tags.push(model.source);
  return {
    id: String(model.id),
    name: model.displayName || model.name,
    tags,
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
  const [uncontrolledIds, setSelectedIds] = useState<Set<string>>(
    () => new Set()
  );
  const selectedIds = useMemo(
    () =>
      selectedModelIds === undefined
        ? uncontrolledIds
        : new Set(selectedModelIds.map(String)),
    [selectedModelIds, uncontrolledIds]
  );
  const [keyword, setKeyword] = useState("");
  const [page, setPage] = useState(1);

  // Base helper: source key for a model (falls back for models without one).
  const sourceOf = (model: ModelOption) => model.source || "unknown";

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

  const allModels = useMemo(() => llmModels.map(toModelItem), [llmModels]);

  const activeModels = useMemo(() => {
    const list = llmModels
      .filter((model) => !activeGroup || sourceOf(model) === activeGroup)
      .map(toModelItem);
    const kw = keyword.trim().toLowerCase();
    if (!kw) return list;
    return list.filter(
      (item) =>
        item.name.toLowerCase().includes(kw) ||
        item.tags.some((tag) => tag.toLowerCase().includes(kw))
    );
  }, [llmModels, activeGroup, keyword]);

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
      (selectedModelIds === undefined
        ? allModels
        : selectedModelIds.flatMap((id) => {
            const item = allModels.find((model) => model.id === String(id));
            return item ? [item] : [];
          })
      )
        .filter((item) => selectedIds.has(item.id))
        .map((item) => ({ id: item.id, label: item.name })),
    [allModels, selectedIds, selectedModelIds]
  );

  const toggleModel = (id: string) => {
    if (disabled) return;
    if (selectedModelIds !== undefined) {
      const modelId = Number(id);
      onSelectionChange?.(
        selectedModelIds.includes(modelId)
          ? selectedModelIds.filter((value) => value !== modelId)
          : [...selectedModelIds, modelId]
      );
      return;
    }
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const activeGroupConf = groups.find((g) => g.key === activeGroup);

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
      showConfirm={false}
      onClose={onClose}
      onConfirm={() => onConfirm?.([])}
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
                const isSelected = selectedIds.has(item.id);
                return (
                  <div
                    key={item.id}
                    className={cn(
                      "flex h-[59px] shrink-0 items-center justify-between rounded-[2px] py-[9px] pl-5 pr-7",
                      isSelected ? "bg-[#E6F2FD]" : "bg-white"
                    )}
                  >
                    <div className="flex items-center gap-3">
                      <span
                        className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-white"
                        style={{
                          background: activeGroupConf?.iconBg ?? "#2E5BFF",
                        }}
                      >
                        <Cpu size={13} />
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
