"use client";

import { useMemo, useState } from "react";

import { Checkbox, Empty, Select, Space, Tag, Typography } from "antd";
import { useTranslation } from "react-i18next";

import {
  getTagDefinitionDisplayName,
  getTagValueDisplayName,
} from "@/lib/systemTagLabels";
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

  const [activeDefinitionId, setActiveDefinitionId] = useState<number | null>(
    null
  );

  const activeDefinition = useMemo(() => {
    const selectedDefinition = activeDefinitions.find(
      (definition) => definition.definition_id === activeDefinitionId
    );
    return selectedDefinition ?? activeDefinitions[0] ?? null;
  }, [activeDefinitionId, activeDefinitions]);

  const selectedTags = useMemo(
    () =>
      activeDefinitions.flatMap((definition) => {
        const selectedValueIds = selectedByDefinition.get(
          definition.definition_id
        );
        if (!selectedValueIds?.length) return [];

        const definitionName = getTagDefinitionDisplayName(
          definition.definition_key,
          definition.definition_name,
          t
        );
        return (definition.values ?? [])
          .filter(
            (tagValue) =>
              selectedValueIds.includes(tagValue.value_id) &&
              tagValue.status === "active"
          )
          .map((tagValue) => ({
            definitionId: definition.definition_id,
            definitionName,
            isNoValue: definition.selection_mode === "no_value",
            valueId: tagValue.value_id,
            valueName: getTagValueDisplayName(
              definition.definition_key,
              tagValue.display_value,
              t
            ),
          }));
      }),
    [activeDefinitions, selectedByDefinition, t]
  );

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

  if (!activeDefinition) return null;

  const definitionName = getTagDefinitionDisplayName(
    activeDefinition.definition_key,
    activeDefinition.definition_name,
    t
  );
  const selectedValueIds =
    selectedByDefinition.get(activeDefinition.definition_id) ?? [];
  const valueOptions = (activeDefinition.values ?? [])
    .filter((tagValue) => tagValue.status === "active")
    .map((tagValue) => ({
      label: getTagValueDisplayName(
        activeDefinition.definition_key,
        tagValue.display_value,
        t
      ),
      value: tagValue.value_id,
    }));
  const isMultiSelect = activeDefinition.selection_mode === "multi_select";
  const isNoValue = activeDefinition.selection_mode === "no_value";
  const noValueId = valueOptions[0]?.value;

  return (
    <Space direction="vertical" className="w-full">
      {selectedTags.length > 0 ? (
        <div className="flex flex-col gap-1">
          <Typography.Text type="secondary" className="text-xs">
            {t("tagManagement.filter.selectedLabel")}
          </Typography.Text>
          <Space wrap size={[4, 4]}>
            {selectedTags.map((tag) => (
              <Tag
                key={`${tag.definitionId}-${tag.valueId}`}
                closable={!disabled}
                onClose={(event) => {
                  event.preventDefault();
                  handleChange(
                    tag.definitionId,
                    (selectedByDefinition.get(tag.definitionId) ?? []).filter(
                      (valueId) => valueId !== tag.valueId
                    )
                  );
                }}
              >
                {tag.isNoValue
                  ? tag.definitionName
                  : `${tag.definitionName}: ${tag.valueName}`}
              </Tag>
            ))}
          </Space>
        </div>
      ) : null}
      <div className="flex flex-col gap-1">
        <Typography.Text type="secondary" className="text-xs">
          {t("tagManagement.filter.definitionLabel")}
        </Typography.Text>
        <Select
          showSearch
          optionFilterProp="label"
          value={activeDefinition.definition_id}
          options={activeDefinitions.map((definition) => {
            const selectedCount =
              selectedByDefinition.get(definition.definition_id)?.length ?? 0;
            const name = getTagDefinitionDisplayName(
              definition.definition_key,
              definition.definition_name,
              t
            );
            return {
              value: definition.definition_id,
              label: selectedCount > 0 ? `${name} (${selectedCount})` : name,
            };
          })}
          onChange={setActiveDefinitionId}
          disabled={disabled}
          style={{ width: "100%" }}
        />
      </div>
      <div className="flex flex-col gap-1">
        <Typography.Text type="secondary" className="text-xs">
          {definitionName}
        </Typography.Text>
        {isNoValue ? (
          <Checkbox
            checked={Boolean(noValueId && selectedValueIds.includes(noValueId))}
            disabled={disabled || !noValueId}
            onChange={(event) =>
              handleChange(
                activeDefinition.definition_id,
                event.target.checked && noValueId ? [noValueId] : []
              )
            }
          >
            {definitionName}
          </Checkbox>
        ) : (
          <Select
            mode={isMultiSelect ? "multiple" : undefined}
            allowClear
            showSearch
            optionFilterProp="label"
            placeholder={t("tagManagement.form.assignPlaceholder")}
            options={valueOptions}
            value={isMultiSelect ? selectedValueIds : selectedValueIds[0]}
            onChange={(nextValue: number | number[] | undefined) => {
              const valueIds = Array.isArray(nextValue)
                ? nextValue
                : nextValue == null
                  ? []
                  : [nextValue];
              handleChange(activeDefinition.definition_id, valueIds);
            }}
            disabled={disabled}
            style={{ width: "100%" }}
            aria-label={t("tagManagement.filter.ariaLabel", {
              definition: definitionName,
            })}
          />
        )}
      </div>
    </Space>
  );
}
