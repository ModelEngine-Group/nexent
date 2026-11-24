// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { SkillRepositoryListingItem } from "../types/skillRepository";

const presentationKinds = new Set([
  "ppt",
  "pptx",
  "powerpoint",
  "presentation",
  "presentations",
  "slides",
  "演示",
  "演示文稿",
  "幻灯片",
]);
const documentKinds = new Set([
  "file",
  "files",
  "document",
  "documents",
  "docx",
  "pdf",
  "xlsx",
  "excel",
  "spreadsheet",
  "spreadsheets",
  "csv",
  "文档",
  "文件",
  "表格",
]);

function classify(value: string) {
  const tokens = value.toLowerCase().split(/[^a-z0-9\u3400-\u9fff]+/);
  if (tokens.some((token) => presentationKinds.has(token))) {
    return "presentation" as const;
  }
  if (tokens.some((token) => documentKinds.has(token))) {
    return "document" as const;
  }
  return undefined;
}

/** Use explicit icon identifiers first; infer only from tags and name, never prose. */
export function getSkillRepositoryIconKind(
  listing: Pick<SkillRepositoryListingItem, "name" | "tags" | "icon">
) {
  const icon = listing.icon?.trim().toLowerCase();
  if (icon === "layers") return "general" as const;
  if (icon === "file-text") return "document" as const;
  if (icon === "presentation") return "presentation" as const;
  return (
    classify((listing.tags ?? []).join(" ")) ??
    classify(listing.name) ??
    "general"
  );
}
