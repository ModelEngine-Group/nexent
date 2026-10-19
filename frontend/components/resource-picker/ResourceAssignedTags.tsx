// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import ResourceTagChips from "@/components/tag/ResourceTagChips";
import TagChips from "@/components/tag/TagChips";
import type {
  TagAssignmentValue,
  TagResourceType,
} from "@/types/tagManagement";

export function ResourceAssignedTags({
  resourceType,
  resourceId,
  tags = [],
  refreshKey,
  max = 3,
  assignments,
}: {
  resourceType: TagResourceType;
  resourceId: string;
  tags?: readonly string[];
  refreshKey?: number;
  max?: number;
  assignments?: TagAssignmentValue[];
}) {
  const fallback = (
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
  );
  if (assignments !== undefined) {
    return assignments.length ? (
      <TagChips assignments={assignments} max={max} />
    ) : (
      fallback
    );
  }
  return (
    <ResourceTagChips
      resourceType={resourceType}
      resourceId={resourceId}
      max={max}
      refreshKey={refreshKey}
      emptyText={fallback}
    />
  );
}
