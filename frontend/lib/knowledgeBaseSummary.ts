// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

export function unwrapKnowledgeBaseSummary(summary: string): string {
  const wrapped = summary.trim();
  if (!wrapped.startsWith("<p>") || !wrapped.endsWith("</p>")) return summary;
  return wrapped.slice(3, -4).replace(/<\/p>\s*<p>/g, "\n\n");
}
