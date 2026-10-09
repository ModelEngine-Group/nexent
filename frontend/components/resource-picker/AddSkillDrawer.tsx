"use client";

import { useEffect, useMemo, useState } from "react";
import { Empty, Spin } from "antd";
import { useTranslation } from "react-i18next";

import { useSkillList } from "@/hooks/agent/useSkillList";
import type { Skill } from "@/types/agentConfig";
import { AddResourceDrawer, ResourceRow } from "./AddResourceDrawer";
import type { ResourceRowItem, SelectedItem } from "./types";

const PAGE_SIZE = 10;

function toSkillRow(skill: Skill): ResourceRowItem {
  return {
    id: String(skill.skill_id),
    name: skill.name,
    tags: skill.tags ?? [],
    description: skill.description ?? "",
    link: (skill.source || "").trim() === "official",
  };
}

export interface AddSkillDrawerProps {
  open: boolean;
  onClose: () => void;
  onConfirm?: (selected: ResourceRowItem[]) => void;
}

export function AddSkillDrawer({ open, onClose, onConfirm }: AddSkillDrawerProps) {
  const { t } = useTranslation("common");
  const { groupedSkills, isLoading } = useSkillList({ enabled: open });
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set());
  const [tab, setTab] = useState("official");
  const [keyword, setKeyword] = useState("");
  const [page, setPage] = useState(1);
  const [tagFilter, setTagFilter] = useState("");

  const tabs = useMemo(
    () => groupedSkills.map((group) => ({ key: group.key, label: group.label })),
    [groupedSkills]
  );

  // Fall back to the first available group when the current tab no longer exists.
  useEffect(() => {
    if (groupedSkills.length > 0 && !groupedSkills.some((group) => group.key === tab)) {
      setTab(groupedSkills[0].key);
    }
  }, [groupedSkills, tab]);

  const allRows = useMemo(
    () => groupedSkills.flatMap((group) => group.skills.map(toSkillRow)),
    [groupedSkills]
  );

  const tagOptions = useMemo(() => {
    const tags = new Set<string>();
    groupedSkills.forEach((group) =>
      group.skills.forEach((skill) =>
        (skill.tags ?? []).forEach((tag) => tags.add(tag))
      )
    );
    return Array.from(tags)
      .sort()
      .map((value) => ({ value, label: value }));
  }, [groupedSkills]);

  const items = useMemo(() => {
    let rows =
      groupedSkills.find((group) => group.key === tab)?.skills.map(toSkillRow) ?? [];
    const kw = keyword.trim().toLowerCase();
    if (kw) {
      rows = rows.filter(
        (item) =>
          item.name.toLowerCase().includes(kw) ||
          item.description.toLowerCase().includes(kw)
      );
    }
    if (tagFilter) {
      rows = rows.filter((item) => item.tags.includes(tagFilter));
    }
    return rows;
  }, [groupedSkills, tab, keyword, tagFilter]);

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
      title={t("resourcePicker.addSkill", "添加技能")}
      searchPlaceholder={t("resourcePicker.search.common", "按名称、描述检索")}
      selected={selected}
      tagOptions={tagOptions}
      listTitle={t("resourcePicker.list.skill", "技能列表")}
      tabs={tabs}
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