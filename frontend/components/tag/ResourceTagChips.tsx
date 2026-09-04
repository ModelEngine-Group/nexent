"use client";

import { useEffect, useState, type ReactNode } from "react";

import TagChips from "@/components/tag/TagChips";
import { tagManagementApi } from "@/services/tagManagementService";
import type { TagAssignmentValue } from "@/types/tagManagement";

interface ResourceTagChipsProps {
  resourceType: string;
  resourceId: string;
  max?: number;
  refreshKey?: string | number;
  singleLine?: boolean;
  emptyText?: ReactNode;
  options?: {
    provider?: string | null;
    knowledgeBaseId?: string | null;
  };
}

/**
 * Compact value-only chips for one resource, loaded on mount and cached by
 * the tag service client. The owning TagChips component keeps the tag name in
 * tooltips and accessibility labels so value-only chips never lose context.
 */
export default function ResourceTagChips({
  resourceType,
  resourceId,
  max,
  refreshKey,
  singleLine,
  emptyText,
  options,
}: ResourceTagChipsProps) {
  const [assignments, setAssignments] = useState<TagAssignmentValue[]>([]);
  // The options object is recreated on every render by callers that omit it;
  // compare its serialized form so an effect only reruns when its content
  // actually changes (and the assignment cache dedupes repeated reads).
  const optionsKey = JSON.stringify(options ?? {});

  useEffect(() => {
    let cancelled = false;
    tagManagementApi
      .getAssignments(resourceType, resourceId, options ?? {})
      .then((result) => {
        if (cancelled) return;
        setAssignments(result.assignments ?? []);
      })
      .catch(() => {
        if (cancelled) return;
        setAssignments([]);
      });
    return () => {
      cancelled = true;
    };
  }, [resourceType, resourceId, optionsKey, refreshKey]);

  if (assignments.length === 0) return emptyText ?? null;
  return (
    <TagChips assignments={assignments} max={max} singleLine={singleLine} />
  );
}
