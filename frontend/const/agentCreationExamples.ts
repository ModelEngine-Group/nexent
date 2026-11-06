// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { BookOpen, Image, Newspaper } from "lucide-react";

/** Shared creation examples and translation keys for workbench and NL2Agent. */
export const AGENT_CREATION_EXAMPLES = [
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
].map((example) => ({
  ...example,
  id: example.key,
  titleKey: `workbench.creationExamples.agent.${example.key}.title`,
  descriptionKey: `workbench.creationExamples.agent.${example.key}.description`,
  promptKey: `workbench.creationExamples.agent.${example.key}`,
}));
