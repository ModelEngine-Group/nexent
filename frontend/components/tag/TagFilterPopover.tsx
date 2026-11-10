// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { Button, Popover, theme } from "antd";
import { DownOutlined } from "@ant-design/icons";
import { Tag } from "lucide-react";
import { useTranslation } from "react-i18next";

import TagFilterControls from "@/components/tag/TagFilterControls";
import {
  getTagDefinitionDisplayName,
  getTagValueDisplayName,
} from "@/lib/systemTagLabels";
import type {
  TagDefinition,
  TagResourcePredicate,
} from "@/types/tagManagement";

interface TagFilterPopoverProps {
  definitions: TagDefinition[];
  value: TagResourcePredicate[];
  onChange: (predicates: TagResourcePredicate[]) => void;
  buttonClassName?: string;
  appearance?: "button" | "select";
}

export default function TagFilterPopover({
  definitions,
  value,
  onChange,
  buttonClassName,
  appearance = "button",
}: TagFilterPopoverProps) {
  const { t } = useTranslation("common");
  const { token } = theme.useToken();
  const selectedLabels =
    appearance === "select"
      ? value.flatMap(({ definition_id, value_ids }) => {
          const definition = definitions.find(
            (item) =>
              item.definition_id === definition_id && item.status === "active"
          );
          if (!definition) return [];

          return (definition.values ?? [])
            .filter(
              (item) =>
                item.status === "active" && value_ids.includes(item.value_id)
            )
            .map((item) =>
              definition.selection_mode === "no_value"
                ? getTagDefinitionDisplayName(
                    definition.definition_key,
                    definition.definition_name,
                    t
                  )
                : getTagValueDisplayName(
                    definition.definition_key,
                    item.display_value,
                    t
                  )
            );
        })
      : [];
  const selectionText = selectedLabels.join(" · ");

  return (
    <Popover
      trigger="click"
      placement="bottomRight"
      content={
        <div className="w-72">
          <TagFilterControls
            definitions={definitions}
            value={value}
            onChange={onChange}
          />
          {value.length > 0 ? (
            <button
              type="button"
              className="mt-2 text-xs text-blue-600 hover:underline"
              onClick={() => onChange([])}
            >
              {t("repository.tagFilter.clear")}
            </button>
          ) : null}
        </div>
      }
    >
      <Button
        type={
          appearance === "button" && value.length > 0 ? "primary" : "default"
        }
        className={buttonClassName}
        aria-label={
          selectionText
            ? `${t("repository.tagFilter.button")}: ${selectionText}`
            : t("repository.tagFilter.button")
        }
        icon={
          appearance === "button" ? (
            <Tag className="size-3.5" aria-hidden />
          ) : undefined
        }
      >
        {appearance === "select" ? (
          <span className="flex w-full min-w-0 items-center justify-between gap-2">
            <span
              className="truncate"
              style={{
                color: selectionText ? undefined : token.colorTextPlaceholder,
              }}
              title={selectionText || undefined}
            >
              {selectionText || t("resourceCenter.tags")}
            </span>
            <DownOutlined
              className="shrink-0 text-xs"
              style={{ color: token.colorTextQuaternary }}
              aria-hidden
            />
          </span>
        ) : (
          t("repository.tagFilter.button")
        )}
      </Button>
    </Popover>
  );
}
