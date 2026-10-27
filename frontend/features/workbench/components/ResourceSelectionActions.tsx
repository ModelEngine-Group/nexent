// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { Button } from "antd";
import { useTranslation } from "react-i18next";

export function ResourceSelectionActions({
  allSelected,
  hasSelection,
  disabled = false,
  empty = false,
  toggleAllDisabled = false,
  onToggleAll,
  onClear,
  pageOnly = false,
}: {
  allSelected: boolean;
  hasSelection: boolean;
  disabled?: boolean;
  empty?: boolean;
  toggleAllDisabled?: boolean;
  onToggleAll: () => void;
  onClear: () => void;
  pageOnly?: boolean;
}) {
  const { t } = useTranslation();
  const label = pageOnly
    ? t(
        allSelected
          ? "workbench.controls.pageClear"
          : "workbench.controls.pageAll",
        allSelected ? "取消本页全选" : "本页全选"
      )
    : t(
        allSelected
          ? "workbench.controls.deselectAll"
          : "workbench.controls.selectAll"
      );
  return (
    <div className="ml-auto flex shrink-0 items-center gap-3">
      <Button
        type="link"
        size="small"
        className="h-auto p-0 font-medium"
        aria-label={label}
        disabled={disabled || empty || toggleAllDisabled}
        title={
          toggleAllDisabled
            ? t("workbench.controls.multiAgentUnavailable")
            : undefined
        }
        onClick={onToggleAll}
      >
        {label}
      </Button>
      <Button
        type="link"
        size="small"
        className="h-auto p-0 font-medium"
        aria-label={t("workbench.controls.clear")}
        disabled={disabled || !hasSelection}
        onClick={onClear}
      >
        {t("workbench.controls.clear")}
      </Button>
    </div>
  );
}
