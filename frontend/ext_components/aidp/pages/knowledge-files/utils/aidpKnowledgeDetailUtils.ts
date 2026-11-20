// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type React from "react";
import type { ColumnsType } from "antd/es/table";

import type {
  AidpDocumentItem,
  AidpKbDetail,
} from "@/ext_components/aidp/shared/types/management";
import { AIDP_UNKNOWN_VALUE } from "@/ext_components/aidp/shared/utils/aidpKnowledgeDisplay";
import {
  AIDP_MIN_COLUMN_WIDTH,
  resizeAidpColumnPair,
} from "@/ext_components/aidp/pages/knowledge-list/utils/aidpKnowledgeColumnWidths";
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

/**
 * Status presentation shared by the file list and the upload-task tab.
 *
 * AIDP is adding the same status field to the folder/file listing, so both
 * surfaces must use one vocabulary: success / extracting / failed / queued /
 * graph failed, plus the remove-failed state when a deployment reports it.
 */
export interface AidpDocumentStatusMeta {
  code: number;
  labelKey: string | null;
  dotClass: string;
}

const DOCUMENT_STATUS_META: Record<
  number,
  { labelKey: string; dotClass: string }
> = {
  1: { labelKey: "aidpKnowledge.taskSuccess", dotClass: "bg-green-500" },
  2: { labelKey: "aidpKnowledge.taskExtracting", dotClass: "bg-blue-500" },
  3: { labelKey: "aidpKnowledge.taskFailed", dotClass: "bg-red-500" },
  4: { labelKey: "aidpKnowledge.taskQueued", dotClass: "bg-gray-400" },
  5: { labelKey: "aidpKnowledge.taskGraphFailed", dotClass: "bg-red-500" },
  6: {
    labelKey: "aidpKnowledge.fileStatusRemoveFailed",
    dotClass: "bg-red-500",
  },
};

export const documentStatusMeta = (
  status: AidpDocumentItem["status"]
): AidpDocumentStatusMeta | null => {
  const code = statusCode(status);
  if (code === null) return null;
  const meta = DOCUMENT_STATUS_META[code];
  return meta
    ? { code, ...meta }
    : { code, labelKey: null, dotClass: "bg-gray-400" };
};

/**
 * Folder/Files status contract (new AIDP API).
 *
 * The folder tree uses numeric 1–6. This is deliberately separate from the
 * legacy document list's ``file_status`` (0/1/2) and from the upload-task
 * vocabulary, where 4 means queued and 5 means graph failed.
 */
export interface AidpFolderTreeStatusPermissions {
  canRename: boolean;
  canMove: boolean;
  canDelete: boolean;
  canPreview: boolean;
  canDownload: boolean;
  canRetry: boolean;
}

export interface AidpFolderTreeStatusMeta extends AidpDocumentStatusMeta {
  permissions: AidpFolderTreeStatusPermissions;
}

const NONE_PERMISSIONS: AidpFolderTreeStatusPermissions = {
  canRename: false,
  canMove: false,
  canDelete: false,
  canPreview: false,
  canDownload: false,
  canRetry: false,
};

const FOLDER_TREE_STATUS_META: Record<
  number,
  {
    labelKey: string;
    dotClass: string;
    permissions: AidpFolderTreeStatusPermissions;
  }
> = {
  1: {
    labelKey: "aidpKnowledge.fileStatusIngested",
    dotClass: "bg-green-500",
    permissions: {
      canRename: true,
      canMove: true,
      canDelete: true,
      canPreview: true,
      canDownload: true,
      canRetry: false,
    },
  },
  2: {
    labelKey: "aidpKnowledge.fileStatusExtracting",
    dotClass: "bg-blue-500",
    permissions: {
      canRename: true,
      canMove: true,
      canDelete: false,
      canPreview: false,
      canDownload: true,
      canRetry: false,
    },
  },
  3: {
    labelKey: "aidpKnowledge.fileStatusFailed",
    dotClass: "bg-red-500",
    permissions: {
      canRename: true,
      canMove: true,
      canDelete: true,
      canPreview: false,
      canDownload: true,
      canRetry: true,
    },
  },
  4: {
    labelKey: "aidpKnowledge.fileStatusGraphFailed",
    dotClass: "bg-orange-500",
    permissions: {
      canRename: true,
      canMove: true,
      canDelete: true,
      canPreview: true,
      canDownload: true,
      canRetry: true,
    },
  },
  5: {
    labelKey: "aidpKnowledge.fileStatusRemoving",
    dotClass: "bg-gray-400",
    permissions: { ...NONE_PERMISSIONS },
  },
  6: {
    labelKey: "aidpKnowledge.fileStatusRemoveFailed",
    dotClass: "bg-red-500",
    permissions: { ...NONE_PERMISSIONS, canDelete: true },
  },
};

// Int 1–6 is the authoritative AIDP folder/file status. String aliases below
// only keep older responses readable until AIDP finishes its status migration.
const folderTreeStatusCode = (
  status: AidpDocumentItem["status"]
): number | null => {
  if (typeof status === "number") {
    return status >= 1 && status <= 6 ? status : null;
  }
  if (typeof status === "string") {
    const trimmed = status.trim();
    if (/^\d+$/.test(trimmed)) {
      const code = Number(trimmed);
      return code >= 1 && code <= 6 ? code : null;
    }
    const aliases: Record<string, number> = {
      COMPLETED: 1,
      SUCCESS: 1,
      PROCESSING: 2,
      EXTRACTING: 2,
      WAITING: 2,
      FAILED: 3,
      VECTOR_INGESTION_FAILED: 3,
      GRAPH_INGESTION_FAILED: 4,
      GRAPH_FAILED: 4,
      REMOVING: 5,
      DELETING: 5,
      REMOVE_FAILED: 6,
      DELETE_FAILED: 6,
    };
    return aliases[trimmed.toUpperCase()] ?? null;
  }
  return null;
};

export const folderTreeStatusMeta = (
  status: AidpDocumentItem["status"]
): AidpFolderTreeStatusMeta | null => {
  const code = folderTreeStatusCode(status);
  if (code === null) return null;
  const meta = FOLDER_TREE_STATUS_META[code];
  return meta ? { code, ...meta, permissions: meta.permissions } : null;
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

export interface AidpFailureReason {
  code?: string | number;
  message?: string;
  raw: string;
}

/** Parse AIDP's JSON-encoded failure reason, falling back to its raw text. */
export const parseAidpFailureReason = (
  value: unknown
): AidpFailureReason | null => {
  if (typeof value !== "string" || !value.trim()) return null;
  const raw = value.trim();
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      const record = parsed as Record<string, unknown>;
      const message = record.msg ?? record.message ?? record.reason;
      const code = record.error_code ?? record.code;
      if (message !== undefined || code !== undefined) {
        return {
          raw,
          ...(message !== undefined &&
          message !== null &&
          String(message).trim()
            ? { message: String(message) }
            : {}),
          ...(typeof code === "string" || typeof code === "number"
            ? { code }
            : {}),
        };
      }
    }
  } catch {
    // Plain-text reasons are rendered as-is.
  }
  return { raw };
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
// acts as the baseline until the user drags a handle. Dragging moves the
// boundary between the column and its next visible neighbour, keeping the
// table's total width stable - the same interaction as the knowledge-base list.
export const withResizableHeaders = <T>(
  columns: ColumnsType<T>,
  columnWidths: Record<string, number>,
  minWidths: Record<string, number>,
  setColumnWidths: React.Dispatch<React.SetStateAction<Record<string, number>>>
): ColumnsType<T> => {
  const keys = columns.map((column) => String(column.key));
  return columns.map((column, index) => {
    const key = keys[index];
    const nextKey = keys[index + 1];
    const nextColumn = columns[index + 1];
    const width =
      columnWidths[key] ??
      (typeof column.width === "number" ? column.width : undefined);
    const nextWidth = nextKey
      ? (columnWidths[nextKey] ??
        (typeof nextColumn?.width === "number" ? nextColumn.width : undefined))
      : undefined;
    const nextMin = nextKey
      ? (minWidths[nextKey] ?? AIDP_MIN_COLUMN_WIDTH)
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
          minWidth: minWidths[key] ?? AIDP_MIN_COLUMN_WIDTH,
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
                    minWidths
                  );
                  // Freeze every rendered width so the table does not
                  // redistribute space after the adjacent pair moves.
                  return { ...current, ...base, ...resized };
                });
              }
            : undefined,
        }) as AidpResizableTitleProps,
    };
  });
};

export const sumColumnWidths = <T>(columns: ColumnsType<T>): number =>
  columns.reduce(
    (sum, column) =>
      sum + (typeof column.width === "number" ? column.width : 0),
    0
  );
