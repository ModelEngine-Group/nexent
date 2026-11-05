// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type HTMLAttributes,
  type Key,
  type ReactNode,
} from "react";
import {
  Table as BaseTable,
  TableHeader,
  TableHead,
  TableBody,
  TableRow,
  TableCell,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { useTranslation } from "react-i18next";
import { Button, type ButtonProps } from "@/components/common/Button";

export interface TableColumn<T> {
  key: string;
  header: ReactNode;
  cell: (row: T) => ReactNode;
  /** Fixed width; omit to size from the rendered content. */
  width?: number;
  minWidth?: number;
  maxWidth?: number;
  /** Share of remaining space; zero keeps the content-sized width. */
  grow?: number;
  resizable?: boolean;
}

export interface TableBulkAction<T> {
  key: string;
  label: ReactNode;
  icon?: ReactNode;
  variant?: ButtonProps["variant"];
  disabled?: boolean;
  loading?: boolean;
  onClick: (rows: readonly T[], clearSelection: () => void) => void;
}

export interface TableSelection<T> {
  selectedKeys?: readonly Key[];
  onChange?: (keys: Key[], rows: T[]) => void;
  isRowSelectable?: (row: T) => boolean;
  getRowLabel?: (row: T) => string;
  disabled?: boolean;
  actions?: readonly TableBulkAction<T>[];
}

/** Native checkboxes retain keyboard behavior and expose the mixed select-all state. */
function SelectionCheckbox({
  checked,
  mixed = false,
  label,
  disabled,
  onChange,
}: {
  checked: boolean;
  mixed?: boolean;
  label: string;
  disabled?: boolean;
  onChange: () => void;
}) {
  return (
    <input
      type="checkbox"
      ref={(input) => {
        if (input) input.indeterminate = mixed;
      }}
      checked={checked}
      aria-checked={mixed ? "mixed" : checked}
      aria-label={label}
      disabled={disabled}
      onChange={onChange}
      className="size-4 shrink-0 cursor-pointer accent-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:cursor-not-allowed disabled:opacity-40"
    />
  );
}

/** Pointer capture keeps resizing scoped to the handle and cleans up on release. */
function ColumnResizeHandle({
  label,
  width,
  minimum,
  maximum,
  onResize,
}: {
  label: string;
  width: number;
  minimum: number;
  maximum: number;
  onResize: (width?: number) => void;
}) {
  const drag = useRef<{ x: number; width: number; pointerId: number } | null>(
    null
  );
  const [dragging, setDragging] = useState(false);
  const clamp = (value: number) =>
    Math.round(Math.min(maximum, Math.max(minimum, value)));
  return (
    <span
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
      aria-valuemin={minimum}
      aria-valuemax={maximum}
      aria-valuenow={Math.round(width)}
      tabIndex={0}
      title={label}
      className={cn(
        "absolute inset-y-0 right-0 z-10 w-2 cursor-col-resize touch-none outline-none after:absolute after:inset-y-3 after:right-0.5 after:w-px after:bg-border hover:after:bg-primary-hover focus-visible:after:bg-primary",
        dragging && "after:bg-primary-active"
      )}
      onClick={(event) => event.stopPropagation()}
      onDoubleClick={(event) => {
        event.stopPropagation();
        onResize();
      }}
      onPointerDown={(event) => {
        if (event.button !== 0 || !event.isPrimary) return;
        event.preventDefault();
        event.stopPropagation();
        drag.current = { x: event.clientX, width, pointerId: event.pointerId };
        event.currentTarget.setPointerCapture(event.pointerId);
        setDragging(true);
      }}
      onPointerMove={(event) => {
        const start = drag.current;
        if (start && start.pointerId === event.pointerId)
          onResize(clamp(start.width + event.clientX - start.x));
      }}
      onPointerUp={(event) => {
        if (drag.current?.pointerId !== event.pointerId) return;
        drag.current = null;
        setDragging(false);
        if (event.currentTarget.hasPointerCapture(event.pointerId))
          event.currentTarget.releasePointerCapture(event.pointerId);
      }}
      onPointerCancel={() => {
        drag.current = null;
        setDragging(false);
      }}
      onLostPointerCapture={() => {
        drag.current = null;
        setDragging(false);
      }}
      onKeyDown={(event) => {
        if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
          event.preventDefault();
          event.stopPropagation();
          onResize(clamp(width + (event.key === "ArrowRight" ? 16 : -16)));
        } else if (event.key === "Enter") {
          event.preventDefault();
          onResize();
        }
      }}
    />
  );
}

export interface TableProps<T> extends Omit<
  HTMLAttributes<HTMLDivElement>,
  "children"
> {
  columns: readonly TableColumn<T>[];
  data: readonly T[];
  rowKey: (row: T) => Key;
  emptyContent?: ReactNode;
  resizable?: boolean;
  columnWidths?: Readonly<Record<string, number>>;
  onColumnWidthsChange?: (widths: Record<string, number>) => void;
  selection?: TableSelection<T>;
}

/** Content-sized columns, bounded growth and shared project presentation. */
export function Table<T>({
  columns,
  data,
  rowKey,
  emptyContent = "—",
  resizable = true,
  columnWidths: controlledWidths,
  onColumnWidthsChange,
  selection,
  className,
  ...props
}: TableProps<T>) {
  const { t } = useTranslation("common");
  const [localWidths, setLocalWidths] = useState<Record<string, number>>({});
  const manualWidths = controlledWidths ?? localWidths;
  const [localSelectedKeys, setLocalSelectedKeys] = useState<Key[]>([]);
  const sourceKeys = selection?.selectedKeys ?? localSelectedKeys;
  const selectableRows = selection
    ? data.filter((row) => selection.isRowSelectable?.(row) !== false)
    : [];
  const selectableKeys = new Set(selectableRows.map(rowKey));
  const selectedKeys = sourceKeys.filter((key) => selectableKeys.has(key));
  const selectedSet = new Set(selectedKeys);
  const selectedRows = selectableRows.filter((row) =>
    selectedSet.has(rowKey(row))
  );
  const selectionBusy = Boolean(
    selection?.disabled || selection?.actions?.some((action) => action.loading)
  );
  const changeSelection = (keys: Key[]) => {
    if (selection?.selectedKeys === undefined) setLocalSelectedKeys(keys);
    const chosen = new Set(keys);
    selection?.onChange?.(
      keys,
      selectableRows.filter((row) => chosen.has(rowKey(row)))
    );
  };
  const clearSelection = () => changeSelection([]);
  useEffect(() => {
    // Visible selection is already filtered; notify owners after the page commits.
    if (!selection || selectedKeys.length === sourceKeys.length) return;
    const frame = requestAnimationFrame(() => changeSelection(selectedKeys));
    return () => cancelAnimationFrame(frame);
  });
  const selectionEnabled = Boolean(selection);
  const table = useRef<HTMLTableElement>(null);
  const header = useRef<HTMLTableSectionElement>(null);
  const body = useRef<HTMLTableSectionElement>(null);
  const [widths, setWidths] = useState<number[]>([]);
  const [scrollbarWidth, setScrollbarWidth] = useState(0);
  const [viewportWidth, setViewportWidth] = useState(0);

  useLayoutEffect(() => {
    const element = table.current;
    const viewport = body.current;
    if (!element || !viewport) return;
    let frame = 0;
    let active = true;
    const measure = () => {
      setScrollbarWidth(viewport.offsetWidth - viewport.clientWidth);
      setViewportWidth(viewport.clientWidth);
      const next = columns.map((column, index) => {
        if (manualWidths[column.key] !== undefined)
          return Math.max(
            column.minWidth ?? 96,
            Math.min(column.maxWidth ?? 4096, manualWidths[column.key])
          );
        if (column.width !== undefined) return column.width;
        const minimum = column.minWidth ?? 96;
        const maximum = Math.max(minimum, column.maxWidth ?? 360);
        const content = element.querySelectorAll<HTMLElement>(
          `[data-table-column="${index}"] [data-table-measure]`
        );
        let measured = 0;
        content.forEach((node) => {
          measured = Math.max(measured, node.scrollWidth);
          node.querySelectorAll<HTMLElement>("*").forEach((child) => {
            if (child instanceof HTMLElement)
              measured = Math.max(measured, child.scrollWidth);
          });
        });
        return Math.min(maximum, Math.max(minimum, measured + 32));
      });
      let remaining =
        viewport.clientWidth -
        (selectionEnabled ? 44 : 0) -
        next.reduce((sum, width) => sum + width, 0);
      // Fit content preferences into the viewport before allowing horizontal scroll.
      // Automatic columns yield first; manual widths also fit after a viewport resize.
      const shrinking = Array.from(columns.keys())
        .filter((index) => columns[index].resizable !== false)
        .sort(
          (left, right) =>
            Number(manualWidths[columns[left].key] !== undefined) -
            Number(manualWidths[columns[right].key] !== undefined)
        );
      for (const index of shrinking) {
        if (remaining >= 0) break;
        const reduction = Math.min(
          -remaining,
          Math.max(0, next[index] - (columns[index].minWidth ?? 96))
        );
        next[index] -= reduction;
        remaining += reduction;
      }
      let growing = Array.from(columns.keys()).filter(
        (index) =>
          columns[index].width === undefined &&
          manualWidths[columns[index].key] === undefined &&
          (columns[index].grow ?? 1) > 0
      );
      // Reallocate space when one of the growing columns reaches its cap.
      while (remaining > 0.5 && growing.length) {
        const weight = growing.reduce(
          (sum, index) => sum + (columns[index].grow ?? 1),
          0
        );
        let allocated = 0;
        for (const index of growing) {
          const maximum = Math.max(
            next[index],
            columns[index].maxWidth ?? Infinity
          );
          const extra = Math.min(
            maximum - next[index],
            (remaining * (columns[index].grow ?? 1)) / weight
          );
          next[index] += extra;
          allocated += extra;
        }
        if (allocated < 0.5) break;
        remaining -= allocated;
        growing = growing.filter(
          (index) => next[index] < (columns[index].maxWidth ?? Infinity)
        );
      }
      setWidths((previous) =>
        previous.length === next.length &&
        previous.every((width, index) => Math.abs(width - next[index]) < 0.5)
          ? previous
          : next
      );
    };
    const schedule = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(measure);
    };
    measure();
    const resize = new ResizeObserver(schedule);
    resize.observe(viewport);
    const content = new MutationObserver(schedule);
    content.observe(element, {
      childList: true,
      characterData: true,
      subtree: true,
    });
    document.fonts?.ready.then(() => {
      if (active) schedule();
    });
    return () => {
      active = false;
      cancelAnimationFrame(frame);
      resize.disconnect();
      content.disconnect();
    };
  }, [columns, data, manualWidths, selectionEnabled]);

  useEffect(() => {
    body.current?.scrollTo({ top: 0 });
  }, [data]);

  const measured = widths.length === columns.length;
  const columnWidths = columns.map((column, index) =>
    measured ? widths[index] : (column.width ?? column.minWidth ?? 96)
  );
  const maximumResizeWidth = (index: number) => {
    const column = columns[index];
    const minimum = column.minWidth ?? 96;
    if (!viewportWidth) return column.maxWidth ?? 4096;
    const reserved = columns.reduce(
      (sum, other, otherIndex) => {
        if (otherIndex === index) return sum;
        return (
          sum +
          (other.resizable === false || manualWidths[other.key] !== undefined
            ? columnWidths[otherIndex]
            : (other.minWidth ?? 96))
        );
      },
      selectionEnabled ? 44 : 0
    );
    return Math.max(
      minimum,
      Math.min(column.maxWidth ?? 4096, viewportWidth - reserved)
    );
  };
  const resizeColumn = (index: number, width?: number) => {
    const column = columns[index];
    const next = { ...manualWidths };
    // Use displayed widths if a previous override was constrained by the viewport.
    columns.forEach((other, otherIndex) => {
      if (next[other.key] !== undefined)
        next[other.key] = columnWidths[otherIndex];
    });
    if (width === undefined) delete next[column.key];
    else
      next[column.key] = Math.min(
        maximumResizeWidth(index),
        Math.max(column.minWidth ?? 96, Math.round(width))
      );
    if (controlledWidths === undefined) setLocalWidths(next);
    onColumnWidthsChange?.(next);
  };
  const layoutWidths = selection ? [44, ...columnWidths] : columnWidths;
  const rowStyle = {
    gridTemplateColumns: layoutWidths.map((width) => `${width}px`).join(" "),
    width: layoutWidths.reduce((sum, width) => sum + width, 0),
  };
  return (
    <div
      {...props}
      className={cn(
        "flex min-h-0 min-w-0 flex-col overflow-hidden rounded-[4px] border border-border bg-background [&>[data-slot=table-container]]:min-h-0 [&>[data-slot=table-container]]:flex-1 [&>[data-slot=table-container]]:overflow-hidden",
        className
      )}
    >
      <BaseTable ref={table} role="table" className="flex h-full flex-col">
        <TableHeader
          ref={header}
          role="rowgroup"
          className="block shrink-0 overflow-hidden bg-muted"
        >
          <TableRow
            role="row"
            className="grid h-11 hover:bg-transparent"
            style={{ ...rowStyle, width: rowStyle.width + scrollbarWidth }}
          >
            {selection && (
              <TableHead
                role="columnheader"
                scope="col"
                className="flex items-center justify-center px-0"
              >
                <SelectionCheckbox
                  label={t("table.selectAll")}
                  checked={
                    selectableRows.length > 0 &&
                    selectedRows.length === selectableRows.length
                  }
                  mixed={
                    selectedRows.length > 0 &&
                    selectedRows.length < selectableRows.length
                  }
                  disabled={selectionBusy || selectableRows.length === 0}
                  onChange={() =>
                    changeSelection(
                      selectedRows.length === selectableRows.length
                        ? []
                        : selectableRows.map(rowKey)
                    )
                  }
                />
              </TableHead>
            )}
            {columns.map((column, index) => (
              <TableHead
                key={column.key}
                scope="col"
                role="columnheader"
                data-table-column={index}
                className="relative flex min-w-0 select-none items-center px-4 font-medium text-muted-foreground"
              >
                <span
                  data-table-measure
                  className="inline-block max-w-full truncate align-middle"
                >
                  {column.header}
                </span>
                {resizable && column.resizable !== false && (
                  <ColumnResizeHandle
                    label={t("table.resizeColumn", {
                      column:
                        typeof column.header === "string"
                          ? column.header
                          : column.key,
                    })}
                    width={columnWidths[index]}
                    minimum={column.minWidth ?? 96}
                    maximum={maximumResizeWidth(index)}
                    onResize={(width) => resizeColumn(index, width)}
                  />
                )}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody
          ref={body}
          role="rowgroup"
          className="block min-h-0 flex-1 overflow-auto"
          onScroll={(event) => {
            if (header.current)
              header.current.scrollLeft = event.currentTarget.scrollLeft;
          }}
        >
          {data.length ? (
            data.map((row) => (
              <TableRow
                key={rowKey(row)}
                role="row"
                aria-selected={
                  selection ? selectedSet.has(rowKey(row)) : undefined
                }
                data-state={
                  selection && selectedSet.has(rowKey(row))
                    ? "selected"
                    : undefined
                }
                className="grid h-[52px] hover:bg-brand-soft/25 data-[state=selected]:bg-brand-soft/50"
                style={rowStyle}
              >
                {selection && (
                  <TableCell
                    role="cell"
                    className="flex items-center justify-center px-0"
                  >
                    <SelectionCheckbox
                      label={t("table.selectRow", {
                        row:
                          selection.getRowLabel?.(row) ?? String(rowKey(row)),
                      })}
                      checked={selectedSet.has(rowKey(row))}
                      disabled={
                        selectionBusy || !selectableKeys.has(rowKey(row))
                      }
                      onChange={() =>
                        changeSelection(
                          selectedSet.has(rowKey(row))
                            ? selectedKeys.filter((key) => key !== rowKey(row))
                            : [...selectedKeys, rowKey(row)]
                        )
                      }
                    />
                  </TableCell>
                )}
                {columns.map((column, index) => (
                  <TableCell
                    key={column.key}
                    role="cell"
                    data-table-column={index}
                    className="flex min-w-0 items-center overflow-hidden px-4 py-3"
                  >
                    <div
                      data-table-measure
                      className="w-max max-w-full truncate"
                    >
                      {column.cell(row)}
                    </div>
                  </TableCell>
                ))}
              </TableRow>
            ))
          ) : (
            <TableRow role="row" className="grid" style={rowStyle}>
              <TableCell
                role="cell"
                style={{ gridColumn: "1 / -1" }}
                colSpan={columns.length + (selection ? 1 : 0)}
                className="flex h-24 items-center justify-center text-muted-foreground"
              >
                {emptyContent}
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </BaseTable>
      {selection && selectedRows.length > 0 && (
        <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-t border-border bg-muted px-4 py-2">
          <span role="status" className="text-sm text-brand-soft-foreground">
            {t("table.selectionCount", { count: selectedRows.length })}
          </span>
          <div className="flex items-center gap-2">
            {selection.actions?.map((action) => (
              <Button
                key={action.key}
                size="sm"
                variant={action.variant ?? "outline"}
                icon={action.icon}
                loading={action.loading}
                disabled={selectionBusy || action.disabled}
                onClick={() => action.onClick(selectedRows, clearSelection)}
              >
                {action.label}
              </Button>
            ))}
            <Button
              size="sm"
              variant="ghost"
              disabled={selectionBusy}
              onClick={clearSelection}
            >
              {t("table.clearSelection")}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
