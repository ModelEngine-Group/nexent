// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useAui, useAuiState } from "@assistant-ui/react";
import { useTranslation } from "react-i18next";
import {
  FileText,
  ClipboardCheck,
  NotebookPen,
  BookOpen,
  Image,
  Newspaper,
} from "lucide-react";
import { CREATION_PROMPTS } from "../state";

const examples = {
  skill_create: [
    { key: "invoiceExtraction", title: "发票信息提取", icon: FileText },
    { key: "contractReview", title: "合同关键信息审查", icon: ClipboardCheck },
    { key: "meetingNotes", title: "会议纪要整理", icon: NotebookPen },
  ],
  agent_create: [
    {
      key: "documentOrganizer",
      title: "文档资料整理助手",
      description: "识别文档，提取要点，生成结构化汇总",
      icon: Image,
    },
    {
      key: "medicalBriefing",
      title: "医学情报简报助手",
      description: "追踪医学进展，制作简报并通过邮件分享",
      icon: Newspaper,
    },
    {
      key: "eventPromotion",
      title: "活动宣传制作助手",
      description: "编写宣传文案，生成配图与活动介绍材料",
      icon: BookOpen,
    },
  ],
};

export function CreationExamples({
  mode,
}: {
  mode: "skill_create" | "agent_create";
}) {
  const aui = useAui();
  const { t } = useTranslation("common");
  const visible = useAuiState(
    (state) =>
      state.thread.messages.length === 0 && state.composer.text.length === 0
  );
  if (!visible) return null;
  return (
    <section
      aria-label={mode === "skill_create" ? "Skill 创建示例" : "Agent创建示例"}
      className="px-1"
    >
      <div className="mb-3 flex items-center gap-2">
        <h2 className="text-sm font-semibold">
          {t("workbench.recommendedPrompts", "推荐提示词")}
        </h2>
      </div>
      <div className="flex flex-col gap-2">
        {examples[mode].map((example, index) => {
          const { key, title, icon: Icon } = example;
          const translationKey = `workbench.creationExamples.${mode === "skill_create" ? "skill" : "agent"}.${key}`;
          const prompt = t(translationKey, CREATION_PROMPTS[mode][index]);
          const cardTitle =
            mode === "agent_create"
              ? t(`${translationKey}.title`, title)
              : title;
          const description =
            "description" in example
              ? t(`${translationKey}.description`, example.description)
              : prompt;
          return (
            <button
              type="button"
              key={key}
              onClick={() => {
                aui.composer().setText(prompt);
                requestAnimationFrame(() =>
                  document
                    .querySelector<HTMLTextAreaElement>(
                      "[data-workbench-composer]"
                    )
                    ?.focus()
                );
              }}
              className="flex w-full min-w-0 items-start gap-3 rounded-xl px-3 py-3 text-left transition-colors hover:bg-accent/50 focus-visible:ring-2"
            >
              <span className="mt-0.5 shrink-0 text-muted-foreground">
                <Icon className="size-4" />
              </span>
              <span className="min-w-0">
                <span className="block text-sm font-medium text-foreground">
                  {cardTitle}
                </span>
                <span className="mt-1 block text-xs leading-5 text-muted-foreground">
                  {description}
                </span>
              </span>
            </button>
          );
        })}
      </div>
    </section>
  );
}
