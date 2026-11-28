// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { Dispatch, SetStateAction } from "react";
import type { ColumnsType } from "antd/es/table";

import {
  sumColumnWidths,
  withResizableHeaders,
} from "@/ext_components/aidp/pages/knowledge-files/utils/aidpKnowledgeDetailUtils";
import { AIDP_MIN_COLUMN_WIDTH } from "@/ext_components/aidp/pages/knowledge-list/utils/aidpKnowledgeColumnWidths";
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
): ColumnsType<AidpSensitiveWordItem> =>
  withResizableHeaders(
    columns.map((column) => ({
      ...column,
      width:
        typeof column.width === "number"
          ? column.width
          : SENSITIVE_WORD_COLUMN_WIDTHS[String(column.key)],
    })),
    columnWidths,
    SENSITIVE_WORD_COLUMN_MIN_WIDTHS,
    setColumnWidths
  );

export const sumSensitiveWordColumnWidths = (
  columns: ColumnsType<AidpSensitiveWordItem>
): number => sumColumnWidths(columns);
