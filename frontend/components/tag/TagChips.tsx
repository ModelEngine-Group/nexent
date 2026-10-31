// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

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
  className?: string;
  tagClassName?: string;
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
  className,
  tagClassName,
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
    let chipText = valueName;
    if (detailed) {
      chipText = label;
    } else if (isNoValue) {
      chipText = definitionName;
    }
    return (
      <Tooltip
        key={`${assignment.definition_id}:${assignment.value_id}`}
        title={label}
      >
        <Tag
          aria-label={label}
          className={`inline-flex max-w-[120px] min-w-0 shrink-0 items-center overflow-hidden ${tagClassName ?? ""}`}
        >
          <span className="min-w-0 truncate">{chipText}</span>
        </Tag>
      </Tooltip>
    );
  };

  const overflowChip = (
    <Tag
      className={`${overflowLabel === undefined ? "" : "cursor-pointer"} ${tagClassName ?? ""}`}
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
      } ${className ?? ""}`}
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
