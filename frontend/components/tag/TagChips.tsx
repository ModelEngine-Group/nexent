"use client";

import { Popover, Tag, Tooltip } from "antd";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import {
  getTagDefinitionDisplayName,
  getTagValueDisplayName,
} from "@/lib/systemTagLabels";
import type { TagAssignmentValue } from "@/types/tagManagement";

interface TagChipsProps {
  assignments: TagAssignmentValue[];
  max?: number;
  singleLine?: boolean;
  overflowLabel?: ReactNode;
}

/**
 * Compact value chips that preserve the owning tag name in the tooltip and
 * accessible label so value-only chips never lose their tag context.
 */
export default function TagChips({
  assignments,
  max = 6,
  singleLine = false,
  overflowLabel,
}: TagChipsProps) {
  const { t } = useTranslation("common");
  const visible = assignments.slice(0, max);
  const overflow = assignments.length - visible.length;

  const renderTag = (assignment: TagAssignmentValue, detailed = false) => {
    const definitionName = getTagDefinitionDisplayName(
      assignment.definition_key,
      assignment.definition_name,
      t
    );
    const valueName = getTagValueDisplayName(
      assignment.definition_key,
      assignment.display_value,
      t
    );
    const isNoValue = assignment.selection_mode === "no_value";
    const label = isNoValue
      ? definitionName
      : `${definitionName}: ${valueName}`;
    return (
      <Tooltip
        key={`${assignment.definition_id}:${assignment.value_id}`}
        title={label}
      >
        <Tag aria-label={label} className="inline-block max-w-[120px] truncate">
          {detailed ? label : isNoValue ? definitionName : valueName}
        </Tag>
      </Tooltip>
    );
  };

  const overflowChip = (
    <Tag
      className={overflowLabel === undefined ? undefined : "cursor-pointer"}
      role={overflowLabel === undefined ? undefined : "button"}
      tabIndex={overflowLabel === undefined ? undefined : 0}
    >
      {overflowLabel ?? `+${overflow}`}
    </Tag>
  );

  return (
    <span
      className={`inline-flex items-center gap-1 ${
        singleLine ? "flex-nowrap" : "flex-wrap"
      }`}
    >
      {visible.map((assignment) => renderTag(assignment))}
      {overflow > 0 &&
        (overflowLabel === undefined ? (
          overflowChip
        ) : (
          <Popover
            trigger="click"
            placement="topLeft"
            content={
              <div className="flex max-w-[360px] flex-wrap gap-1">
                {assignments.map((assignment) => renderTag(assignment, true))}
              </div>
            }
          >
            {overflowChip}
          </Popover>
        ))}
    </span>
  );
}
