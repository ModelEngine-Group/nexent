"use client";

import { useMemo, useState } from "react";
import { Database } from "lucide-react";
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";
import { AddResourceDrawer, CheckMark } from "./AddResourceDrawer";
import type { KnowledgeItem, SelectedItem } from "./types";

const MOCK_KNOWLEDGE: KnowledgeItem[] = [
  {
    id: "1",
    name: "市场监督知识库",
    category: "市场",
    iconBg: "#8B7BF6",
    description:
      "本知识库聚焦大健康基础科普指引，涵盖饮食营养、运动健身、作息睡眠、慢病预防、体检解读等健康知识，包含知识要点、常见误区、日常建议、风险提示等常见问答答案，为用户提供一站式、标准化的健康生活参考。",
    meta: ["2025-03-25 使用过", "7文档", "18块"],
  },
  {
    id: "2",
    name: "麻醉知识库",
    category: "医学知识",
    iconBg: "#7B5BF2",
    description:
      "本知识库聚焦大健康基础科普指引，涵盖饮食营养、运动健身、作息睡眠、慢病预防、体检解读等健康知识，包含知识要点、常见误区、日常建议、风险提示等常见问答答案，为用户提供一站式、标准化的健康生活参考。",
    meta: ["2025-03-25 使用过", "7文档", "18块"],
  },
  {
    id: "3",
    name: "皮肤科基础医疗知识库",
    category: "医学知识",
    iconBg: "#9F8CF8",
    description:
      "本知识库聚焦大健康基础科普指引，涵盖饮食营养、运动健身、作息睡眠、慢病预防、体检解读等健康知识，包含知识要点、常见误区、日常建议、风险提示等常见问答答案，为用户提供一站式、标准化的健康生活参考。",
    meta: ["2025-03-25 使用过", "7文档", "18块"],
  },
  {
    id: "4",
    name: "骨科知识库",
    category: "医学知识",
    iconBg: "#8B7BF6",
    description:
      "本知识库聚焦大健康基础科普指引，涵盖饮食营养、运动健身、作息睡眠、慢病预防、体检解读等健康知识，包含知识要点、常见误区、日常建议、风险提示等常见问答答案，为用户提供一站式、标准化的健康生活参考。",
    meta: ["2025-03-25 使用过", "7文档", "18块"],
  },
  {
    id: "5",
    name: "心血管疾病专家知识库",
    category: "医学知识",
    iconBg: "#7B5BF2",
    description:
      "本知识库聚焦大健康基础科普指引，涵盖饮食营养、运动健身、作息睡眠、慢病预防、体检解读等健康知识，包含知识要点、常见误区、日常建议、风险提示等常见问答答案，为用户提供一站式、标准化的健康生活参考。",
    meta: ["2025-03-25 使用过", "7文档", "18块"],
  },
];

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
  const [selectedIds, setSelectedIds] = useState<Set<string>>(
    () => new Set(["1", "2"])
  );
  const [keyword, setKeyword] = useState("");

  const items = useMemo(
    () =>
      MOCK_KNOWLEDGE.filter(
        (item) =>
          !keyword ||
          item.name.includes(keyword) ||
          item.description.includes(keyword)
      ),
    [keyword]
  );

  const selected: SelectedItem[] = useMemo(
    () =>
      MOCK_KNOWLEDGE.filter((item) => selectedIds.has(item.id)).map((item) => ({
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
      title={t("resourcePicker.addKnowledge", "添加知识库")}
      searchPlaceholder={t("resourcePicker.search.knowledge", "搜索知识库名称及描述")}
      selected={selected}
      tagOptions={[{ value: "tag", label: t("resourcePicker.tag", "标签") }]}
      listTitle={t("resourcePicker.list.knowledge", "知识库列表")}
      total={500}
      showConfirm
      onClose={onClose}
      onConfirm={() =>
        onConfirm?.(MOCK_KNOWLEDGE.filter((item) => selectedIds.has(item.id)))
      }
      onRemoveSelected={(id) => toggle(id)}
      onSearch={setKeyword}
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
      <div className="flex flex-col gap-2">
        {items.map((item) => (
          <KnowledgeRow
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