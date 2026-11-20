// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { Dispatch, SetStateAction } from "react";
import type { ColumnsType } from "antd/es/table";

import type { AidpResizableTitleProps } from "@/ext_components/aidp/pages/knowledge-list/AidpResizableTitle";
import {
  AIDP_MIN_COLUMN_WIDTH,
  resizeAidpColumnPair,
} from "@/ext_components/aidp/pages/knowledge-list/utils/aidpKnowledgeColumnWidths";
import type { AidpSensitiveWordItem } from "@/ext_components/aidp/shared/types/sensitiveWord";

export const SENSITIVE_WORD_COLUMN_WIDTHS: Record<string, number> = {
  index: 72,
  word: 240,
  mode: 120,
  description: 360,
  actions: 140,
};

export const SENSITIVE_WORD_COLUMN_MIN_WIDTHS: Record<string, number> = {
  index: AIDP_MIN_COLUMN_WIDTH,
  word: 140,
  mode: 100,
  description: 160,
  actions: 120,
};

/** Apply the same drag-to-resize headers used by the KB and file lists. */
export const withResizableSensitiveWordColumns = (
  columns: ColumnsType<AidpSensitiveWordItem>,
  columnWidths: Record<string, number>,
  setColumnWidths: Dispatch<SetStateAction<Record<string, number>>>
): ColumnsType<AidpSensitiveWordItem> => {
  const keys = columns.map((column) => String(column.key));
  return columns.map((column, index) => {
    const key = keys[index];
    const nextKey = keys[index + 1];
    const nextColumn = columns[index + 1];
    const width =
      columnWidths[key] ??
      (typeof column.width === "number"
        ? column.width
        : SENSITIVE_WORD_COLUMN_WIDTHS[key]);
    const nextWidth = nextKey
      ? (columnWidths[nextKey] ??
        (typeof nextColumn?.width === "number"
          ? nextColumn.width
          : SENSITIVE_WORD_COLUMN_WIDTHS[nextKey]))
      : undefined;
    const nextMin = nextKey
      ? (SENSITIVE_WORD_COLUMN_MIN_WIDTHS[nextKey] ?? AIDP_MIN_COLUMN_WIDTH)
      : undefined;
    const maxWidth =
      typeof width === "number" &&
      typeof nextWidth === "number" &&
      typeof nextMin === "number"
        ? width + nextWidth - nextMin
        : undefined;
    return {
      ...column,
      width,
      onHeaderCell: () =>
        ({
          width,
          minWidth:
            SENSITIVE_WORD_COLUMN_MIN_WIDTHS[key] ?? AIDP_MIN_COLUMN_WIDTH,
          maxWidth,
          "data-column-key": key,
          onResize: nextKey
            ? (delta: number, renderedWidths: Record<string, number>) => {
                setColumnWidths((current) => {
                  const base = {
                    ...current,
                    ...renderedWidths,
                    [key]:
                      renderedWidths[key] ?? columnWidths[key] ?? width ?? 0,
                    [nextKey]:
                      renderedWidths[nextKey] ??
                      columnWidths[nextKey] ??
                      nextWidth ??
                      0,
                  };
                  const resized = resizeAidpColumnPair(
                    base,
                    key,
                    nextKey,
                    delta,
                    SENSITIVE_WORD_COLUMN_MIN_WIDTHS
                  );
                  return { ...current, ...base, ...resized };
                });
              }
            : undefined,
        }) as AidpResizableTitleProps,
    };
  });
};

export const sumSensitiveWordColumnWidths = (
  columns: ColumnsType<AidpSensitiveWordItem>
): number =>
  columns.reduce(
    (sum, column) =>
      sum + (typeof column.width === "number" ? column.width : 0),
    0
  );
