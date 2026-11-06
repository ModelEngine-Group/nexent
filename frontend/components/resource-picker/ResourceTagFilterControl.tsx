// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { Alert, Button, Spin } from "antd";
import { useTranslation } from "react-i18next";
import TagFilterPopover from "@/components/tag/TagFilterPopover";
import type { useResourceTagFilter } from "@/hooks/useResourceTagFilter";

export function ResourceTagFilterControl({
  filter,
  onChange,
}: {
  filter: ReturnType<typeof useResourceTagFilter>;
  onChange: () => void;
}) {
  const { t } = useTranslation("common");
  return (
    <div className="shrink-0">
      <div className="flex items-center gap-2">
        <TagFilterPopover
          definitions={filter.definitions}
          value={filter.predicates}
          onChange={(value) => {
            filter.setPredicates(value);
            onChange();
          }}
        />
        {(filter.loading || filter.filtering) && <Spin size="small" />}
      </div>
      {filter.error && (
        <Alert
          className="mt-2 max-w-72"
          type="error"
          title={filter.error}
          action={
            <Button size="small" onClick={filter.retry}>
              {t("common.retry", "重试")}
            </Button>
          }
        />
      )}
    </div>
  );
}
