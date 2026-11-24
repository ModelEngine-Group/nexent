// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { OPS_PAGES } from "@/const/navigationPages";

const pageRoutes = new Map<string, string>(
  Object.values(OPS_PAGES).map(({ pageId, path }) => [pageId, path])
);

export function resolveAccessibleRoutes(pageIds: readonly string[]): string[] {
  const routes = pageIds.flatMap((pageId) => {
    // Existing page grants may still be stored as absolute paths.
    const path =
      pageRoutes.get(pageId) ?? (pageId.startsWith("/") ? pageId : null);
    return path ? [path] : [];
  });
  return [...new Set(routes)];
}
