"use client";

import { useMemo, useState } from "react";
import { Bot } from "lucide-react";
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";
import { AddResourceDrawer, CheckMark } from "./AddResourceDrawer";
import type { AgentCardItem, SelectedItem } from "./types";

const MOCK_AGENTS: AgentCardItem[] = [
  {
    id: "1",
    name: "健康小助手",
    description:
      "一个专业、全面的健康管理咨询助手，致力于为用户提供可靠、实用的健康信息与生活指导。",
    iconBg: "#8B7BF6",
    publishedAt: "2026-01-23",
    online: false,
  },
  {
    id: "2",
    name: "健康小助手",
    description:
      "一个专业、全面的健康管理咨询助手，致力于为用户提供可靠、实用的健康信息与生活指导。",
    iconBg: "#5B8DEF",
    publishedAt: "2026-01-23",
    online: true,
  },
  {
    id: "3",
    name: "健康小助手",
    description:
      "一个专业、全面的健康管理咨询助手，致力于为用户提供可靠、实用的健康信息与生活指导。",
    iconBg: "#7B5BF2",
    publishedAt: "2026-01-23",
    online: false,
  },
  {
    id: "4",
    name: "健康小助手",
    description:
      "一个专业、全面的健康管理咨询助手，致力于为用户提供可靠、实用的健康信息与生活指导。",
    iconBg: "#3B82F6",
    publishedAt: "2026-01-23",
    online: false,
  },
  {
    id: "5",
    name: "健康小助手",
    description:
      "一个专业、全面的健康管理咨询助手，致力于为用户提供可靠、实用的健康信息与生活指导。",
    iconBg: "#8B7BF6",
    publishedAt: "2026-01-23",
    online: false,
  },
  {
    id: "6",
    name: "健康小助手",
    description:
      "一个专业、全面的健康管理咨询助手，致力于为用户提供可靠、实用的健康信息与生活指导。",
    iconBg: "#2E5BFF",
    publishedAt: "2026-01-23",
    online: false,
  },
];

function AgentCard({
  item,
  selected,
  onToggle,
}: {
  item: AgentCardItem;
  selected: boolean;
  onToggle: () => void;
}) {
  return (
    <div
      className={cn(
        "relative flex h-[149px] flex-col gap-1.5 rounded-[8px] border p-3",
        selected ? "border-[#7EB6F0] bg-[#E6F2FD]" : "border-[#D9D9D9] bg-white"
      )}
    >
      <div className="absolute right-3 top-3">
        <CheckMark checked={selected} onToggle={onToggle} />
      </div>
      <div className="flex items-center gap-2.5">
        <div
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[8px] text-white"
          style={{ background: item.iconBg }}
        >
          <Bot size={20} />
        </div>
        <span className="text-[14px] font-medium leading-[22px] text-[#191919]">
          {item.name}
        </span>
      </div>
      <p className="line-clamp-2 text-[14px] leading-[20px] text-[#737373]">
        {item.description}
      </p>
      <div className="mt-auto flex gap-3.5 text-[12px] leading-[18px] text-[#999]">
        <span>🕑 发布于 {item.publishedAt}</span>
        <span>⊙ {item.online ? "已上线" : "未上线"}</span>
      </div>
    </div>
  );
}

export interface AddAgentDrawerProps {
  open: boolean;
  onClose: () => void;
  onConfirm?: (selected: AgentCardItem[]) => void;
}

export function AddAgentDrawer({ open, onClose, onConfirm }: AddAgentDrawerProps) {
  const { t } = useTranslation("common");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(
    () => new Set(["1"])
  );
  const [tab, setTab] = useState("local");
  const [keyword, setKeyword] = useState("");

  const agents = useMemo(
    () =>
      MOCK_AGENTS.filter(
        (item) =>
          !keyword ||
          item.name.includes(keyword) ||
          item.description.includes(keyword)
      ),
    [keyword]
  );

  const selected: SelectedItem[] = useMemo(
    () =>
      MOCK_AGENTS.filter((item) => selectedIds.has(item.id)).map((item) => ({
        id: item.id,
        label: item.name,
      })),
    [selectedIds]
  );

  const allSelected = agents.length > 0 && agents.every((a) => selectedIds.has(a.id));

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
      title={t("resourcePicker.addAgent", "添加子智能体")}
      searchPlaceholder={t("resourcePicker.search.agent", "按名称、描述检索")}
      selected={selected}
      tagOptions={[{ value: "tag", label: "标签" }]}
      listTitle={t("resourcePicker.list.agent", "智能体列表")}
      tabs={[
        { key: "local", label: t("resourcePicker.tab.localAgent", "本地智能体") },
        { key: "external", label: t("resourcePicker.tab.externalAgent", "外部智能体") },
      ]}
      activeTab={tab}
      total={500}
      showConfirm
      onClose={onClose}
      onConfirm={() => onConfirm?.(MOCK_AGENTS.filter((a) => selectedIds.has(a.id)))}
      onRemoveSelected={(id) => toggle(id)}
      onSearch={setKeyword}
      onTabChange={setTab}
      onSelectAll={(checked) =>
        setSelectedIds(new Set(checked ? agents.map((a) => a.id) : []))
      }
      allSelected={allSelected}
    >
      <div className="grid grid-cols-2 content-start gap-2">
        {agents.map((item) => (
          <AgentCard
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