// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import ResourceTagChips from "@/components/tag/ResourceTagChips";
import type { TagResourceType } from "@/types/tagManagement";

export function ResourceAssignedTags({
  resourceType,
  resourceId,
  tags = [],
  refreshKey,
  max = 3,
}: {
  resourceType: TagResourceType;
  resourceId: string;
  tags?: readonly string[];
  refreshKey?: number;
  max?: number;
}) {
  return (
    <ResourceTagChips
      resourceType={resourceType}
      resourceId={resourceId}
      max={max}
      refreshKey={refreshKey}
      emptyText={
        <>
          {[...new Set(tags)].map((tag) => (
            <span
              key={tag}
              className="shrink-0 rounded bg-muted px-1.5 text-xs text-muted-foreground"
            >
              {tag}
            </span>
          ))}
        </>
      }
    />
  );
}
