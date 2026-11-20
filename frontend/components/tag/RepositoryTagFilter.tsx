// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { Button, Popover, Select } from "antd";
import { Tag } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useRepositoryPresentation } from "@/hooks/useRepositoryPresentation";

export interface RepositoryTagStat {
  tag: string;
  count: number;
}

interface RepositoryTagFilterProps {
  value?: string;
  tags: RepositoryTagStat[];
  onChange: (value?: string) => void;
}

export default function RepositoryTagFilter({
  value,
  tags,
  onChange,
}: RepositoryTagFilterProps) {
  const { t } = useTranslation("common");
  const presentation = useRepositoryPresentation();

  if (presentation) {
    return (
      <Select
        aria-label={t("repository.tagFilter.button")}
        allowClear
        showSearch
        className="w-[240px] max-w-full"
        value={value}
        placeholder={t("resourceCenter.tags")}
        optionFilterProp="label"
        optionLabelProp="value"
        options={tags.map(({ tag, count }) => ({
          value: tag,
          label: `${tag} (${count})`,
        }))}
        onChange={onChange}
      />
    );
  }

  return (
    <Popover
      trigger="click"
      placement="bottomRight"
      content={
        <div className="w-64">
          <Select
            allowClear
            showSearch
            className="w-full"
            value={value}
            placeholder={t("repository.tagFilter.placeholder")}
            optionFilterProp="label"
            options={tags.map(({ tag, count }) => ({
              value: tag,
              label: `${tag} (${count})`,
            }))}
            onChange={(nextValue?: string) => onChange(nextValue)}
          />
          {value ? (
            <button
              type="button"
              className="mt-2 text-xs text-blue-600 hover:underline"
              onClick={() => onChange(undefined)}
            >
              {t("repository.tagFilter.clear")}
            </button>
          ) : null}
        </div>
      }
    >
      <Button
        type={value ? "primary" : "default"}
        icon={<Tag className="size-3.5" aria-hidden />}
      >
        {t("repository.tagFilter.button")}
      </Button>
    </Popover>
  );
}
