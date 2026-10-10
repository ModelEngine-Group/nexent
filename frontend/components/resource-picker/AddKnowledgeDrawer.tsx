"use client";

import { useEffect, useMemo, useState } from "react";
import { Database } from "lucide-react";
import { Empty, Spin } from "antd";
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useKnowledgeList } from "@/hooks/knowledge/useKnowledgeList";
import { formatDate } from "@/lib/date";
import type { KnowledgeBase } from "@/types/knowledgeBase";
import { AddResourceDrawer, CheckMark } from "./AddResourceDrawer";
import type { KnowledgeItem, SelectedItem } from "./types";

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

function toKnowledgeItem(kb: KnowledgeBase): KnowledgeItem {
  const meta: string[] = [];
  const usedAt = formatDate(kb.updatedAt);
  if (usedAt) meta.push(`${usedAt} 使用过`);
  meta.push(`${kb.documentCount}文档`);
  meta.push(`${kb.chunkCount}块`);
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
}: {
  item: KnowledgeItem;
  selected: boolean;
  onToggle: () => void;
}) {
  return (
    <div
      className={cn(
        "flex min-h-[120px] shrink-0 items-center gap-3 rounded-[2px] px-5 py-[9px]",
        selected ? "bg-[#E6F2FD]" : "bg-white"
      )}
    >
      <div
        className="flex h-6 w-6 shrink-0 items-center justify-center rounded-[4px] text-white"
        style={{ background: item.iconBg }}
      >
        <Database size={13} />
      </div>
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <div className="flex items-center gap-2">
          <span className="truncate text-[14px] leading-[22px] text-[#2673E5]">
            {item.name}
          </span>
          {item.category && (
            <span className="h-[18px] shrink-0 rounded-[2px] bg-[#F5F5F5] px-2 text-[12px] leading-[18px] text-[#4D4D4D]">
              {item.category}
            </span>
          )}
        </div>
        <p className="line-clamp-2 text-[14px] leading-[20px] text-[#737373]">
          {item.description}
        </p>
        <div className="flex items-center gap-2.5 text-[12px] leading-[18px] text-[#999]">
          {item.meta.map((text, i) => (
            <span key={text} className="flex items-center gap-2.5">
              {i > 0 && <span className="h-2.5 w-px bg-[#DDD]" />}
              {text}
            </span>
          ))}
        </div>
      </div>
      <CheckMark checked={selected} onToggle={onToggle} />
    </div>
  );
}

export interface AddKnowledgeDrawerProps {
  open: boolean;
  onClose: () => void;
  onConfirm?: (selected: KnowledgeItem[]) => void;
}

export function AddKnowledgeDrawer({
  open,
  onClose,
  onConfirm,
}: AddKnowledgeDrawerProps) {
  const { t } = useTranslation("common");
  const { user } = useAuthorizationContext();
  const tenantId = user?.tenantId ?? null;
  const { data: knowledgeBases, isLoading, refetch } = useKnowledgeList(tenantId);

  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set());
  const [keyword, setKeyword] = useState("");
  const [page, setPage] = useState(1);
  const [tagFilter, setTagFilter] = useState("");

  const allItems = useMemo(() => (knowledgeBases ?? []).map(toKnowledgeItem), [
    knowledgeBases,
  ]);

  // Knowledge bases carry no user tags; expose the real `source` (来源) as the filter.
  const tagOptions = useMemo(() => {
    const sources = new Set<string>();
    allItems.forEach((item) => {
      if (item.category) sources.add(item.category);
    });
    return Array.from(sources)
      .sort()
      .map((value) => ({ value, label: value }));
  }, [allItems]);

  const items = useMemo(() => {
    let filtered = allItems;
    const kw = keyword.trim().toLowerCase();
    if (kw) {
      filtered = filtered.filter(
        (item) =>
          item.name.toLowerCase().includes(kw) ||
          item.description.toLowerCase().includes(kw)
      );
    }
    if (tagFilter) {
      filtered = filtered.filter((item) => item.category === tagFilter);
    }
    return filtered;
  }, [allItems, keyword, tagFilter]);

  // Reset to the first page whenever the search or tag changes.
  useEffect(() => {
    setPage(1);
  }, [keyword, tagFilter]);

  const pagedItems = items.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  const selected: SelectedItem[] = useMemo(
    () =>
      allItems
        .filter((item) => selectedIds.has(item.id))
        .map((item) => ({ id: item.id, label: item.name })),
    [allItems, selectedIds]
  );

  const allSelected = items.length > 0 && items.every((item) => selectedIds.has(item.id));

  const toggle = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <AddResourceDrawer
      open={open}
      title={t("resourcePicker.addKnowledge", "添加知识库")}
      searchPlaceholder={t("resourcePicker.search.knowledge", "搜索知识库名称及描述")}
      selected={selected}
      tagOptions={tagOptions}
      listTitle={t("resourcePicker.list.knowledge", "知识库列表")}
      total={items.length}
      page={page}
      onPageChange={setPage}
      showConfirm
      onClose={onClose}
      onConfirm={() => onConfirm?.(allItems.filter((item) => selectedIds.has(item.id)))}
      onRemoveSelected={(id) => toggle(id)}
      onSearch={setKeyword}
      onTagChange={(value) => setTagFilter(value ?? "")}
      onRefresh={() => refetch()}
      onSelectAll={(checked) =>
        setSelectedIds(new Set(checked ? items.map((item) => item.id) : []))
      }
      allSelected={allSelected}
      selectedTrailing={
        <button
          type="button"
          className="flex h-6 cursor-pointer items-center border-0 bg-transparent p-0 text-[12px] leading-[24px] text-[#2673E5]"
        >
          {t("resourcePicker.expand", "等 22 个 展开 ∨")}
        </button>
      }
    >
      {isLoading ? (
        <div className="flex justify-center py-12">
          <Spin />
        </div>
      ) : items.length === 0 ? (
        <Empty description={t("resourcePicker.empty", "暂无数据")} />
      ) : (
        <div className="flex flex-col gap-2">
          {pagedItems.map((item) => (
            <KnowledgeRow
              key={item.id}
              item={item}
              selected={selectedIds.has(item.id)}
              onToggle={() => toggle(item.id)}
            />
          ))}
        </div>
      )}
    </AddResourceDrawer>
  );
}