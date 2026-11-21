// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { Input, Select, Switch, Tooltip } from "antd";
import { Info } from "lucide-react";
import { useTranslation } from "react-i18next";

import type {
  AidpMetadataFilter,
  AidpMetadataFilterOperator,
} from "@/types/knowledgeScope";

const OPERATOR_OPTIONS: Array<{
  value: AidpMetadataFilterOperator;
  labelKey: string;
  defaultLabel: string;
}> = [
  {
    value: "contains",
    labelKey: "chat.knowledgeScope.filterOperatorContains",
    defaultLabel: "包含",
  },
  {
    value: "is",
    labelKey: "chat.knowledgeScope.filterOperatorIs",
    defaultLabel: "等于",
  },
  {
    value: "starts_with",
    labelKey: "chat.knowledgeScope.filterOperatorStartsWith",
    defaultLabel: "开头是",
  },
  {
    value: "ends_with",
    labelKey: "chat.knowledgeScope.filterOperatorEndsWith",
    defaultLabel: "结尾是",
  },
];

interface AdvancedMetadataFilterProps {
  value: AidpMetadataFilter;
  disabled?: boolean;
  onChange: (value: AidpMetadataFilter) => void;
}

export function AdvancedMetadataFilter({
  value,
  disabled = false,
  onChange,
}: AdvancedMetadataFilterProps) {
  const { t } = useTranslation();
  const enabled = Boolean(value.enabled);
  const operator = value.file_name?.operator ?? "contains";
  const text = value.file_name?.value ?? "";

  const updateCondition = (
    nextOperator: AidpMetadataFilterOperator,
    nextText: string
  ) =>
    onChange({
      enabled: true,
      file_name: { operator: nextOperator, value: nextText },
    });

  return (
    <div className="border-t border-border px-1 pb-1 pt-3">
      <div className="flex items-center gap-2">
        <span className="text-[14px] font-medium">
          {t("chat.knowledgeScope.advancedFilter", "高级筛选")}
        </span>
        <Tooltip
          title={t(
            "chat.knowledgeScope.advancedFilterHint",
            "按文件元数据限制进入检索的 chunk"
          )}
        >
          <Info
            className="size-3.5 text-muted-foreground"
            aria-label={t(
              "chat.knowledgeScope.advancedFilterHint",
              "按文件元数据限制进入检索的 chunk"
            )}
          />
        </Tooltip>
        <Switch
          size="small"
          checked={enabled}
          disabled={disabled}
          onChange={(checked) =>
            onChange(
              checked
                ? {
                    enabled: true,
                    file_name: { operator, value: text },
                  }
                : { enabled: false }
            )
          }
        />
        {!enabled ? (
          <span className="ml-auto text-xs text-muted-foreground">
            {t(
              "chat.knowledgeScope.advancedFilterOffHint",
              "开启开关进行高级筛选设置"
            )}
          </span>
        ) : null}
      </div>
      {enabled ? (
        <div className="mt-2 space-y-2">
          <p className="text-xs text-muted-foreground">
            {t(
              "chat.knowledgeScope.advancedFilterOnHint",
              "设定高级筛选后，满足筛选规则的 chunk 才会被检索"
            )}
          </p>
          <div>
            <div className="mb-1.5 text-[13px]">
              {t("chat.knowledgeScope.filterFileName", "文件名")}
            </div>
            <div className="flex gap-2">
              <Select
                className="w-24 shrink-0"
                value={operator}
                disabled={disabled}
                options={OPERATOR_OPTIONS.map((option) => ({
                  value: option.value,
                  label: t(option.labelKey, option.defaultLabel),
                }))}
                onChange={(nextOperator) => updateCondition(nextOperator, text)}
              />
              <Input
                value={text}
                disabled={disabled}
                allowClear
                maxLength={256}
                placeholder={t(
                  "chat.knowledgeScope.filterFileNamePlaceholder",
                  "请输入文件名关键词"
                )}
                onChange={(event) =>
                  updateCondition(operator, event.target.value)
                }
              />
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
