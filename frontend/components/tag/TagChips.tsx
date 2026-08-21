"use client";

import { Tag, Tooltip } from "antd";

import type { TagAssignmentValue } from "@/types/tagManagement";

interface TagChipsProps {
  assignments: TagAssignmentValue[];
  max?: number;
}

/**
 * Compact value chips that preserve the owning tag name in the tooltip and
 * accessible label so value-only chips never lose their tag context.
 */
export default function TagChips({ assignments, max = 6 }: TagChipsProps) {
  const visible = assignments.slice(0, max);
  const overflow = assignments.length - visible.length;

  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      {visible.map((assignment) => {
        const label = `${assignment.definition_name}: ${assignment.display_value}`;
        return (
          <Tooltip
            key={`${assignment.definition_id}:${assignment.value_id}`}
            title={label}
          >
            <Tag aria-label={label}>{assignment.display_value}</Tag>
          </Tooltip>
        );
      })}
      {overflow > 0 && (
        <Tag>
          {"+"}
          {overflow}
        </Tag>
      )}
    </span>
  );
}
