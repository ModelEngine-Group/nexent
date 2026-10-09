"use client";

import { useEffect, useMemo, useState } from "react";
import { Empty, Spin } from "antd";
import { useTranslation } from "react-i18next";
import i18n from "i18next";

import { useToolList } from "@/hooks/agent/useToolList";
import { TOOL_SOURCE_TYPES } from "@/const/agentConfig";
import type { Tool } from "@/types/agentConfig";
import { AddResourceDrawer, ResourceRow } from "./AddResourceDrawer";
import type { ResourceRowItem, SelectedItem } from "./types";

const PAGE_SIZE = 10;

function getToolDescription(tool: Tool): string {
  const locale = i18n.language || "en";
  if (locale.startsWith("zh") && tool.description_zh) {
    return tool.description_zh;
  }
  return tool.description ?? "";
}

function toToolRow(tool: Tool): ResourceRowItem {
  return {
    id: tool.id,
    name: tool.name,
    tags: Array.isArray(tool.labels) ? tool.labels : [],
    description: getToolDescription(tool),
  };
}

export interface AddToolDrawerProps {
  open: boolean;
  onClose: () => void;
  onConfirm?: (selected: ResourceRowItem[]) => void;
}

export function AddToolDrawer({ open, onClose, onConfirm }: AddToolDrawerProps) {
  const { t } = useTranslation("common");
  const { selectableTools, isLoading } = useToolList({ enabled: open });
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set());
  const [tab, setTab] = useState("local");
  const [keyword, setKeyword] = useState("");
  const [page, setPage] = useState(1);
  const [tagFilter, setTagFilter] = useState("");

  const allRows = useMemo(() => selectableTools.map(toToolRow), [selectableTools]);

  const tagOptions = useMemo(() => {
    const labels = new Set<string>();
    selectableTools.forEach((tool: Tool) =>
      (tool.labels ?? []).forEach((label) => labels.add(label))
    );
    return Array.from(labels)
      .sort()
      .map((value) => ({ value, label: value }));
  }, [selectableTools]);

  const items = useMemo(() => {
    const source = tab === "mcp" ? TOOL_SOURCE_TYPES.MCP : TOOL_SOURCE_TYPES.LOCAL;
    let rows = selectableTools
      .filter((tool) => tool.source === source)
      .map(toToolRow);
    const kw = keyword.trim().toLowerCase();
    if (kw) {
      rows = rows.filter(
        (item) =>
          item.name.toLowerCase().includes(kw) ||
          item.description.toLowerCase().includes(kw) ||
          item.tags.some((tag) => tag.toLowerCase().includes(kw))
      );
    }
    if (tagFilter) {
      rows = rows.filter((item) => item.tags.includes(tagFilter));
    }
    return rows;
  }, [selectableTools, tab, keyword, tagFilter]);

  // Reset to the first page whenever the search, tag or tab changes.
  useEffect(() => {
    setPage(1);
  }, [keyword, tagFilter, tab]);

  const pagedItems = items.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  const selected: SelectedItem[] = useMemo(
    () =>
      allRows
        .filter((item) => selectedIds.has(item.id))
        .map((item) => ({ id: item.id, label: item.name })),
    [allRows, selectedIds]
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
      title={t("resourcePicker.addTool", "添加工具")}
      searchPlaceholder={t("resourcePicker.search.common", "按名称、描述检索")}
      selected={selected}
      tagOptions={tagOptions}
      listTitle={t("resourcePicker.list.tool", "工具列表")}
      tabs={[
        { key: "local", label: t("resourcePicker.tab.localTool", "本地工具") },
        { key: "mcp", label: t("resourcePicker.tab.mcp", "MCP服务") },
      ]}
      activeTab={tab}
      total={items.length}
      page={page}
      onPageChange={setPage}
      showConfirm
      onClose={onClose}
      onConfirm={() => onConfirm?.(allRows.filter((item) => selectedIds.has(item.id)))}
      onRemoveSelected={(id) => toggle(id)}
      onSearch={setKeyword}
      onTagChange={(value) => setTagFilter(value ?? "")}
      onTabChange={setTab}
      onSelectAll={(checked) =>
        setSelectedIds(new Set(checked ? items.map((item) => item.id) : []))
      }
      allSelected={allSelected}
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
            <ResourceRow
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