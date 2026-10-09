"use client";

import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { AddResourceDrawer, ResourceRow } from "./AddResourceDrawer";
import type { ResourceRowItem, SelectedItem } from "./types";

const MOCK_TOOLS: ResourceRowItem[] = [
  {
    id: "t1",
    name: "search-web-tavily",
    tags: ["search", "web"],
    description: "使用 Tavily API 提供互联网搜索能力。当用户需要搜索实时信息等非专有数据时使用此工具",
    link: true,
  },
  {
    id: "t2",
    name: "search-web-tavily",
    tags: ["knowledge"],
    description: "使用 Tavily API 提供互联网搜索能力。当用户需要搜索实时信息等非专有数据时使用此工具",
  },
  {
    id: "t3",
    name: "search-web-tavily",
    tags: ["knowledge"],
    description: "使用 Tavily API 提供互联网搜索能力。当用户需要搜索实时信息等非专有数据时使用此工具",
  },
  {
    id: "t4",
    name: "search-web-tavily",
    tags: ["knowledge"],
    description: "使用 Tavily API 提供互联网搜索能力。当用户需要搜索实时信息等非专有数据时使用此工具",
  },
  {
    id: "t5",
    name: "search-web-tavily",
    tags: ["search", "web"],
    description: "使用 Tavily API 提供互联网搜索能力。当用户需要搜索实时信息等非专有数据时使用此工具",
    link: true,
  },
  {
    id: "t6",
    name: "search-web-tavily",
    tags: ["knowledge"],
    description: "使用 Tavily API 提供互联网搜索能力。当用户需要搜索实时信息等非专有数据时使用此工具",
  },
];

export interface AddToolDrawerProps {
  open: boolean;
  onClose: () => void;
  onConfirm?: (selected: ResourceRowItem[]) => void;
}

export function AddToolDrawer({ open, onClose, onConfirm }: AddToolDrawerProps) {
  const { t } = useTranslation("common");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(
    () => new Set(["t1"])
  );
  const [tab, setTab] = useState("local");
  const [keyword, setKeyword] = useState("");

  const items = useMemo(
    () =>
      MOCK_TOOLS.filter(
        (item) =>
          !keyword ||
          item.name.includes(keyword) ||
          item.description.includes(keyword)
      ),
    [keyword]
  );

  const selected: SelectedItem[] = useMemo(
    () =>
      MOCK_TOOLS.filter((item) => selectedIds.has(item.id)).map((item) => ({
        id: item.id,
        label: item.name,
      })),
    [selectedIds]
  );

  const allSelected =
    items.length > 0 && items.every((item) => selectedIds.has(item.id));

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
      tagOptions={[{ value: "tag", label: t("resourcePicker.tag", "标签") }]}
      listTitle={t("resourcePicker.list.tool", "工具列表")}
      tabs={[
        { key: "local", label: t("resourcePicker.tab.localTool", "本地工具") },
        { key: "mcp", label: t("resourcePicker.tab.mcp", "MCP服务") },
      ]}
      activeTab={tab}
      total={500}
      showConfirm
      onClose={onClose}
      onConfirm={() => onConfirm?.(MOCK_TOOLS.filter((item) => selectedIds.has(item.id)))}
      onRemoveSelected={(id) => toggle(id)}
      onSearch={setKeyword}
      onTabChange={setTab}
      onSelectAll={(checked) =>
        setSelectedIds(new Set(checked ? items.map((item) => item.id) : []))
      }
      allSelected={allSelected}
    >
      <div className="flex flex-col gap-2">
        {items.map((item) => (
          <ResourceRow
            key={item.id}
            item={item}
            selected={selectedIds.has(item.id)}
            onToggle={() => toggle(item.id)}
          />
        ))}
      </div>
    </AddResourceDrawer>
  );
}