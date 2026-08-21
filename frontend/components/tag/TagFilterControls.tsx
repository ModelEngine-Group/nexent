"use client";

import { useMemo } from "react";

import { Empty, Select, Space, Typography } from "antd";
import { useTranslation } from "react-i18next";

import type {
  TagDefinition,
  TagDocumentPredicate,
} from "@/types/tagManagement";

interface TagFilterControlsProps {
  definitions: TagDefinition[];
  value: TagDocumentPredicate[];
  onChange: (predicates: TagDocumentPredicate[]) => void;
  disabled?: boolean;
}

/**
 * Structured tag filter controls with OR-within a definition and AND-across
 * definitions semantics. Each definition renders one multi-select of its
 * controlled values; the emitted predicates carry only non-empty groups.
 */
export default function TagFilterControls({
  definitions,
  value,
  onChange,
  disabled = false,
}: TagFilterControlsProps) {
  const { t } = useTranslation("common");

  const activeDefinitions = useMemo(
    () => definitions.filter((definition) => definition.status === "active"),
    [definitions]
  );

  const selectedByDefinition = useMemo(() => {
    const map = new Map<number, number[]>();
    for (const predicate of value) {
      map.set(predicate.definition_id, predicate.value_ids);
    }
    return map;
  }, [value]);

  const handleChange = (definitionId: number, valueIds: number[]) => {
    const next = value.filter(
      (predicate) => predicate.definition_id !== definitionId
    );
    if (valueIds.length > 0) {
      next.push({ definition_id: definitionId, value_ids: valueIds });
    }
    onChange(next);
  };

  if (activeDefinitions.length === 0) {
    return (
      <Empty
        description={t("tagManagement.empty.noActiveDefinitions")}
        image={Empty.PRESENTED_IMAGE_SIMPLE}
      />
    );
  }

  return (
    <Space direction="vertical" className="w-full">
      {activeDefinitions.map((definition) => {
        const options = (definition.values ?? [])
          .filter((tagValue) => tagValue.status === "active")
          .map((tagValue) => ({
            label: tagValue.display_value,
            value: tagValue.value_id,
          }));
        return (
          <div key={definition.definition_id} className="flex flex-col gap-1">
            <Typography.Text type="secondary" className="text-xs">
              {definition.definition_name}
            </Typography.Text>
            <Select
              mode="multiple"
              allowClear
              placeholder={t("tagManagement.form.assignPlaceholder")}
              options={options}
              value={selectedByDefinition.get(definition.definition_id) ?? []}
              onChange={(valueIds: number[]) =>
                handleChange(definition.definition_id, valueIds)
              }
              disabled={disabled}
              style={{ width: "100%" }}
              aria-label={t("tagManagement.filter.ariaLabel", {
                definition: definition.definition_name,
              })}
            />
          </div>
        );
      })}
    </Space>
  );
}
