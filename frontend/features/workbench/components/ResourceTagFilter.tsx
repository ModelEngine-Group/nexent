// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { Alert, Button } from "antd";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import TagFilterPopover from "@/components/tag/TagFilterPopover";
import type { useResourceTags } from "../hooks/useResourceTags";

export function ResourceTagFilter({
  filter,
  onChange,
  search,
  showFilter = true,
}: {
  filter: ReturnType<typeof useResourceTags>;
  onChange?: () => void;
  search?: ReactNode;
  showFilter?: boolean;
}) {
  const { t } = useTranslation();
  return (
    <div className="space-y-2">
      <div className="flex min-w-0 items-center gap-2" data-resource-search-row>
        {search && <div className="min-w-0 flex-1">{search}</div>}
        {showFilter && (
          <div className="shrink-0">
            <TagFilterPopover
              definitions={filter.definitions}
              value={filter.predicates}
              onChange={(value) => {
                filter.setPredicates(value);
                onChange?.();
              }}
            />
          </div>
        )}
      </div>
      {showFilter && filter.error && (
        <Alert
          type="error"
          title={filter.error}
          action={
            <Button size="small" onClick={() => filter.retry?.()}>
              {t("common.retry", "重试")}
            </Button>
          }
        />
      )}
    </div>
  );
}
