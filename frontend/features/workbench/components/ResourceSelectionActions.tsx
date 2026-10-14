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
    : allSelected
      ? "取消全选"
      : "全选";
  return (
    <div className="ml-auto flex shrink-0 items-center gap-3">
      <Button
        type="link"
        size="small"
        className="h-auto p-0 font-medium"
        aria-label={label}
        disabled={disabled || empty || toggleAllDisabled}
        title={toggleAllDisabled ? "当前环境未启用多智能体模式" : undefined}
        onClick={onToggleAll}
      >
        {label}
      </Button>
      <Button
        type="link"
        size="small"
        className="h-auto p-0 font-medium"
        aria-label="清空"
        disabled={disabled || !hasSelection}
        onClick={onClear}
      >
        清空
      </Button>
    </div>
  );
}
