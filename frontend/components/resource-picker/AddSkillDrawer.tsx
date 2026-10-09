"use client";

import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { AddResourceDrawer, ResourceRow } from "./AddResourceDrawer";
import type { ResourceRowItem, SelectedItem } from "./types";

const MOCK_SKILLS: ResourceRowItem[] = [
  {
    id: "s1",
    name: "search-web-tavily",
    tags: ["search", "web"],
    description: "使用 Tavily API 提供互联网搜索能力。当用户需要搜索当下的信息等非专有数据时使用此工具",
    link: true,
  },
  {
    id: "s2",
    name: "search-web-batch",
    tags: ["search", "knowledge"],
    description: "使用 Tavily API 提供互联网搜索能力。当用户需要搜索当下的信息等非专有数据时使用此工具",
  },
  {
    id: "s3",
    name: "search-web-linkup",
    tags: ["search", "knowledge"],
    description: "使用 Tavily API 提供互联网搜索能力。当用户需要搜索当下的信息等非专有数据时使用此工具",
  },
  {
    id: "s4",
    name: "search-knowledge-base",
    tags: ["search", "knowledge"],
    description: "使用 Tavily API 提供互联网搜索能力。当用户需要搜索当下的信息等非专有数据时使用此工具",
  },
  {
    id: "s5",
    name: "search-web-tavily",
    tags: ["search", "web"],
    description: "使用 Tavily API 提供互联网搜索能力。当用户需要搜索当下的信息等非专有数据时使用此工具",
    link: true,
  },
  {
    id: "s6",
    name: "search-web-arkse",
    tags: ["search", "knowledge"],
    description: "使用 Tavily API 提供互联网搜索能力。当用户需要搜索当下的信息等非专有数据时使用此工具",
  },
];

export interface AddSkillDrawerProps {
  open: boolean;
  onClose: () => void;
  onConfirm?: (selected: ResourceRowItem[]) => void;
}

export function AddSkillDrawer({ open, onClose, onConfirm }: AddSkillDrawerProps) {
  const { t } = useTranslation("common");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(
    () => new Set(["s1"])
  );
  const [tab, setTab] = useState("official");
  const [keyword, setKeyword] = useState("");

  const items = useMemo(
    () =>
      MOCK_SKILLS.filter(
        (item) =>
          !keyword ||
          item.name.includes(keyword) ||
          item.description.includes(keyword)
      ),
    [keyword]
  );

  const selected: SelectedItem[] = useMemo(
    () =>
      MOCK_SKILLS.filter((item) => selectedIds.has(item.id)).map((item) => ({
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
      title={t("resourcePicker.addSkill", "添加技能")}
      searchPlaceholder={t("resourcePicker.search.common", "按名称、描述检索")}
      selected={selected}
      tagOptions={[{ value: "tag", label: t("resourcePicker.tag", "标签") }]}
      listTitle={t("resourcePicker.list.skill", "技能列表")}
      tabs={[
        { key: "official", label: t("resourcePicker.tab.official", "官方") },
        { key: "custom", label: t("resourcePicker.tab.custom", "自定义") },
      ]}
      activeTab={tab}
      total={500}
      showConfirm
      onClose={onClose}
      onConfirm={() => onConfirm?.(MOCK_SKILLS.filter((item) => selectedIds.has(item.id)))}
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