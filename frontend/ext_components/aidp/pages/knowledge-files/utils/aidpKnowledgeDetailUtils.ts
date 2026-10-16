// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type React from "react";
import type { ColumnsType } from "antd/es/table";

import type {
  AidpDocumentItem,
  AidpKbDetail,
} from "@/ext_components/aidp/shared/types/management";
import { AIDP_UNKNOWN_VALUE } from "@/ext_components/aidp/shared/utils/aidpKnowledgeDisplay";
import { AIDP_MIN_COLUMN_WIDTH } from "@/ext_components/aidp/pages/knowledge-list/utils/aidpKnowledgeColumnWidths";
import type { AidpResizableTitleProps } from "@/ext_components/aidp/pages/knowledge-list/AidpResizableTitle";

/** Default page size shared by the files and upload-task lists. */
export const AIDP_DETAIL_PAGE_SIZE = 10;

export const formatDetailDateTime = (value: unknown): string => {
  let date: Date;
  if (typeof value === "number" && Number.isFinite(value)) {
    date = new Date(value < 1e12 ? value * 1000 : value);
  } else if (typeof value === "string" && value.trim()) {
    const normalized = value.trim();
    const numeric = /^\d+(?:\.\d+)?$/.test(normalized)
      ? Number(normalized)
      : null;
    date =
      numeric === null
        ? new Date(normalized)
        : new Date(numeric < 1e12 ? numeric * 1000 : numeric);
  } else {
    return AIDP_UNKNOWN_VALUE;
  }
  if (Number.isNaN(date.getTime())) return AIDP_UNKNOWN_VALUE;
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  });
};

export const formatFailureTaskDateTime = (value: unknown): string => {
  let date: Date;
  if (typeof value === "number" && Number.isFinite(value)) {
    date = new Date(value < 1e12 ? value * 1000 : value);
  } else if (typeof value === "string" && value.trim()) {
    const normalized = value.trim();
    const numeric = /^\d+(?:\.\d+)?$/.test(normalized)
      ? Number(normalized)
      : null;
    date =
      numeric === null
        ? new Date(normalized)
        : new Date(numeric < 1e12 ? numeric * 1000 : numeric);
  } else {
    return AIDP_UNKNOWN_VALUE;
  }
  if (Number.isNaN(date.getTime())) return AIDP_UNKNOWN_VALUE;
  const pad = (part: number) => String(part).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
};

export const formatFileSize = (bytes?: number): string => {
  if (typeof bytes !== "number" || !Number.isFinite(bytes) || bytes < 0) {
    return AIDP_UNKNOWN_VALUE;
  }
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) {
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
};

export const statusCode = (
  status: AidpDocumentItem["status"]
): number | null => {
  if (typeof status === "number") return status;
  if (typeof status === "string" && /^\d+$/.test(status.trim())) {
    return Number(status);
  }
  const aliases: Record<string, number> = {
    COMPLETED: 1,
    SUCCESS: 1,
    PROCESSING: 2,
    EXTRACTING: 2,
    FAILED: 3,
    VECTOR_INGESTION_FAILED: 3,
    UPLOADING: 4,
    QUEUED: 4,
    GRAPH_INGESTION_FAILED: 5,
  };
  return typeof status === "string"
    ? (aliases[status.toUpperCase()] ?? null)
    : null;
};

/** Normalize an ingested file's delete status to its numeric contract.
 *
 * AIDP reports ``file_status`` as ``0`` (ingested), ``1`` (deleting) or
 * ``2`` (delete failed); numeric strings are accepted because deployments
 * have been observed to quote numbers. Any other value, including missing
 * ones, falls back to ``0`` so the row still reads "ingested".
 */
export const fileDeleteStatusCode = (value: unknown): 0 | 1 | 2 => {
  const code =
    typeof value === "number"
      ? value
      : typeof value === "string" && /^\d+$/.test(value.trim())
        ? Number(value.trim())
        : null;
  return code === 1 || code === 2 ? code : 0;
};

export const graphConfigOf = (
  detail: AidpKbDetail
): Record<string, unknown> => {
  const raw = detail.graph_config;
  if (raw && typeof raw === "object") return raw;
  if (typeof raw === "string") {
    try {
      const parsed = JSON.parse(raw) as unknown;
      return parsed && typeof parsed === "object"
        ? (parsed as Record<string, unknown>)
        : {};
    } catch {
      return {};
    }
  }
  return {};
};

export const FILE_COLUMN_MIN_WIDTHS: Record<string, number> = {
  file_name: 120,
  file_type: 60,
  file_size: 70,
  import_mode: 80,
  created_at: 100,
  updated_at: 100,
  file_status: 90,
  actions: 120,
};

export const TASK_COLUMN_MIN_WIDTHS: Record<string, number> = {
  file_name: 120,
  file_type: 60,
  file_size: 70,
  updated_at: 100,
  status: 90,
  actions: 175,
};

// Attach the resizable header cell to every column; the declared column width
// acts as the baseline until the user drags a handle. The resize handle reports
// a pointer delta plus a snapshot of the rendered widths, so the dragged
// column's next width is derived from its rendered baseline and all other
// columns are frozen at their rendered widths.
export const withResizableHeaders = (
  columns: ColumnsType<AidpDocumentItem>,
  columnWidths: Record<string, number>,
  minWidths: Record<string, number>,
  setColumnWidths: React.Dispatch<React.SetStateAction<Record<string, number>>>
): ColumnsType<AidpDocumentItem> =>
  columns.map((column) => {
    const key = String(column.key);
    const width =
      columnWidths[key] ??
      (typeof column.width === "number" ? column.width : undefined);
    return {
      ...column,
      width,
      onHeaderCell: () =>
        ({
          width,
          minWidth: minWidths[key] ?? AIDP_MIN_COLUMN_WIDTH,
          "data-column-key": key,
          onResize: (delta: number, renderedWidths: Record<string, number>) => {
            setColumnWidths((current) => {
              const base =
                renderedWidths[key] ?? columnWidths[key] ?? width ?? 0;
              const next = Math.max(
                minWidths[key] ?? AIDP_MIN_COLUMN_WIDTH,
                Math.round(base + delta)
              );
              // Freeze the rendered widths first so only the dragged column
              // changes and the browser does not redistribute spare space.
              return { ...current, ...renderedWidths, [key]: next };
            });
          },
        }) as AidpResizableTitleProps,
    };
  });

export const sumColumnWidths = (
  columns: ColumnsType<AidpDocumentItem>
): number =>
  columns.reduce(
    (sum, column) =>
      sum + (typeof column.width === "number" ? column.width : 0),
    0
  );
