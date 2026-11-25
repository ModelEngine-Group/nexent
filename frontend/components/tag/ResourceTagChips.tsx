// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useEffect, useState, type ReactNode } from "react";

import TagChips from "@/components/tag/TagChips";
import { tagManagementApi } from "@/services/tagManagementService";
import { subscribeToAssignmentChanges } from "@/services/tagAssignmentCache";
import type { TagAssignmentValue } from "@/types/tagManagement";

interface ResourceTagChipsProps {
  resourceType: string;
  resourceId: string;
  max?: number;
  overflowLabel?: ReactNode;
  refreshKey?: string | number;
  singleLine?: boolean;
  emptyText?: ReactNode;
  className?: string;
  tagClassName?: string;
  options?: {
    provider?: string | null;
    knowledgeBaseId?: string | null;
  };
}

/**
 * Compact value-only chips for one resource, reloaded on resource invalidation
 * and cached by the tag service client. The owning TagChips component keeps the
 * tag name in tooltips and accessibility labels so value-only chips never lose context.
 */
export default function ResourceTagChips({
  resourceType,
  resourceId,
  max,
  overflowLabel,
  refreshKey,
  singleLine,
  emptyText,
  className,
  tagClassName,
  options,
}: ResourceTagChipsProps) {
  const [assignments, setAssignments] = useState<TagAssignmentValue[]>([]);
  // The options object is recreated on every render by callers that omit it;
  // compare its serialized form so an effect only reruns when its content
  // actually changes (and the assignment cache dedupes repeated reads).
  const optionsKey = JSON.stringify(options ?? {});

  useEffect(() => {
    let cancelled = false;
    let requestId = 0;
    const refresh = () => {
      const currentRequest = ++requestId;
      tagManagementApi
        .getAssignments(resourceType, resourceId, options ?? {})
        .then((result) => {
          if (cancelled || currentRequest !== requestId) return;
          setAssignments(result.assignments ?? []);
        })
        .catch(() => {
          if (cancelled || currentRequest !== requestId) return;
          setAssignments([]);
        });
    };
    const unsubscribe = subscribeToAssignmentChanges(
      resourceType,
      resourceId,
      refresh
    );
    refresh();
    return () => {
      cancelled = true;
      unsubscribe();
    };
  }, [resourceType, resourceId, optionsKey, refreshKey]);

  if (assignments.length === 0) return emptyText ?? null;
  return (
    <TagChips
      assignments={assignments}
      max={max}
      overflowLabel={overflowLabel}
      singleLine={singleLine}
      className={className}
      tagClassName={tagClassName}
    />
  );
}
