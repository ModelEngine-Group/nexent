import { Button } from "antd";

export function ResourceSelectionActions({
  allSelected,
  hasSelection,
  disabled = false,
  empty = false,
  onToggleAll,
  onClear,
}: {
  allSelected: boolean;
  hasSelection: boolean;
  disabled?: boolean;
  empty?: boolean;
  onToggleAll: () => void;
  onClear: () => void;
}) {
  return (
    <div className="ml-auto flex shrink-0 items-center gap-3">
      <Button
        type="link"
        size="small"
        className="h-auto p-0 font-medium"
        aria-label={allSelected ? "取消全选" : "全选"}
        disabled={disabled || empty}
        onClick={onToggleAll}
      >
        {allSelected ? "取消全选" : "全选"}
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
