"use client";

import { Tag, Tooltip } from "antd";
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
}

/**
 * Compact value chips that preserve the owning tag name in the tooltip and
 * accessible label so value-only chips never lose their tag context.
 */
export default function TagChips({
  assignments,
  max = 6,
  singleLine = false,
}: TagChipsProps) {
  const { t } = useTranslation("common");
  const visible = assignments.slice(0, max);
  const overflow = assignments.length - visible.length;

  return (
    <span
      className={`inline-flex items-center gap-1 ${
        singleLine ? "flex-nowrap" : "flex-wrap"
      }`}
    >
      {visible.map((assignment) => {
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
            <Tag aria-label={label}>
              {isNoValue ? definitionName : valueName}
            </Tag>
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
