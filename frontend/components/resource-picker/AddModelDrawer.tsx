"use client";

import { useMemo, useState } from "react";
import { Cpu } from "lucide-react";
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";
import { AddResourceDrawer } from "./AddResourceDrawer";
import type { ModelGroup, ModelItem, SelectedItem } from "./types";

const MOCK_GROUPS: ModelGroup[] = [
  { key: "doubao", label: "豆包", icon: "豆", iconBg: "#4D6BFE" },
  { key: "qwen", label: "通义千问", icon: "通", iconBg: "#7B5BF2" },
  { key: "deepseek", label: "DeepSeek", icon: "DS", iconBg: "#2E5BFF" },
  { key: "zhipu", label: "智谱", icon: "智", iconBg: "#3B82F6" },
  { key: "moonshot", label: "月之暗面", icon: "月", iconBg: "#1F2329" },
];

const MOCK_MODELS: Record<string, ModelItem[]> = {
  doubao: [
    { id: "d1", name: "doubao-1.5-pro-32k", tags: ["128k", "文本推理", "工具调用"] },
    { id: "d2", name: "doubao-pro-32k", tags: ["128k", "文本推理", "工具调用"] },
    { id: "d3", name: "doubao-lite-32k", tags: ["128k", "文本推理", "工具调用"] },
  ],
  qwen: [
    { id: "q1", name: "qwen-max", tags: ["128k", "文本推理", "工具调用"] },
    { id: "q2", name: "qwen-plus", tags: ["128k", "文本推理", "工具调用"] },
    { id: "q3", name: "qwen-turbo", tags: ["128k", "文本推理", "工具调用"] },
  ],
  deepseek: [
    { id: "v1", name: "deepseek-v4.1-flash", tags: ["1000k", "文本推理", "深度思考", "工具调用"] },
    { id: "v2", name: "deepseek-reasoner", tags: ["1000k", "文本推理", "工具调用"] },
    { id: "v3", name: "deepseek-chat", tags: ["1000k", "文本推理", "工具调用"] },
    { id: "v4", name: "deepseek-v4-pro", tags: ["1000k", "文本推理", "工具调用"] },
    { id: "v5", name: "deepseek-v4-flash", tags: ["1000k", "文本推理", "工具调用"] },
    { id: "v6", name: "deepseek-v3.2", tags: ["1000k", "文本推理", "工具调用"] },
  ],
  zhipu: [
    { id: "z1", name: "glm-4-plus", tags: ["128k", "文本推理", "工具调用"] },
    { id: "z2", name: "glm-4-air", tags: ["128k", "文本推理", "工具调用"] },
  ],
  moonshot: [
    { id: "m1", name: "moonshot-v1-8k", tags: ["8k", "文本推理", "工具调用"] },
    { id: "m2", name: "moonshot-v1-32k", tags: ["32k", "文本推理", "工具调用"] },
  ],
};

export interface AddModelDrawerProps {
  open: boolean;
  onClose: () => void;
  onConfirm?: (selected: ModelItem[]) => void;
}

export function AddModelDrawer({ open, onClose, onConfirm }: AddModelDrawerProps) {
  const { t } = useTranslation("common");
  const [activeGroup, setActiveGroup] = useState("deepseek");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(
    () => new Set(["v1"])
  );
  const [keyword, setKeyword] = useState("");

  const activeModels = useMemo(() => {
    const list = MOCK_MODELS[activeGroup] ?? [];
    return list.filter(
      (item) =>
        !keyword || item.name.includes(keyword) || item.tags.some((tag) => tag.includes(keyword))
    );
  }, [activeGroup, keyword]);

  const selected: SelectedItem[] = useMemo(() => {
    const all = Object.values(MOCK_MODELS).flat();
    return all
      .filter((item) => selectedIds.has(item.id))
      .map((item) => ({ id: item.id, label: item.name }));
  }, [selectedIds]);

  const toggleModel = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const activeGroupConf = MOCK_GROUPS.find((g) => g.key === activeGroup);

  return (
    <AddResourceDrawer
      open={open}
      title={t("resourcePicker.addModel", "添加模型")}
      searchPlaceholder={t("resourcePicker.search.model", "按名称、描述检索")}
      selected={selected}
      listTitle={t("resourcePicker.list.model", "模型列表")}
      total={500}
      showConfirm={false}
      onClose={onClose}
      onConfirm={() => onConfirm?.([])}
      onRemoveSelected={(id) => toggleModel(id)}
      onSearch={setKeyword}
    >
      <div className="flex h-full gap-4">
        <div className="flex w-[216px] shrink-0 flex-col gap-1">
          {MOCK_GROUPS.map((group) => (
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
          {activeModels.map((item) => {
            const isSelected = selectedIds.has(item.id);
            return (
              <div
                key={item.id}
                onClick={() => toggleModel(item.id)}
                className={cn(
                  "flex h-[59px] shrink-0 cursor-pointer items-center justify-between rounded-[2px] py-[9px] pl-5 pr-7",
                  isSelected ? "bg-[#E6F2FD]" : "bg-white"
                )}
              >
                <div className="flex items-center gap-3">
                  <span
                    className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-white"
                    style={{ background: activeGroupConf?.iconBg ?? "#2E5BFF" }}
                  >
                    <Cpu size={13} />
                  </span>
                  <div className="flex min-w-0 flex-col gap-0.5">
                    <span
                      className={cn(
                        "truncate text-[14px] leading-[22px]",
                        isSelected ? "font-medium text-[#0067D1]" : "font-medium text-[#191919]"
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
              </div>
            );
          })}
        </div>
      </div>
    </AddResourceDrawer>
  );
}