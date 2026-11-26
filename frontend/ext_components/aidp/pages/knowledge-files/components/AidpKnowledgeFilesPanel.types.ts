// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { AidpDocumentItem, AidpFolderFileItem, AidpKbDetail } from "@/ext_components/aidp/shared/types/management";

export interface AidpKnowledgeFilesPanelProps {
  knowledgeBase: AidpKbDetail;
  canEdit: boolean;
  isAvailable: boolean;
  /** Open one file in the routed file-detail page. */
  onOpenFile: (file: AidpDocumentItem, folderPath: string) => void;
  /** Reflect the current folder in the knowledge base URL. */
  onFolderChange: (folderPath: string) => void;
  /** Folder restored from the URL after returning from a file detail. */
  initialPath?: string;
  pollingPaused?: boolean;
  onFilesChanged?: () => void;
}

export type FolderTableRow = {
  key: string;
  kind: "folder";
  name: string;
  path: string;
};

export type FileTableRow = {
  key: string;
  kind: "file";
  name: string;
  file: AidpFolderFileItem;
};

export type FileTableRecord = FolderTableRow | FileTableRow;

export type FolderNameDialog =
  | { mode: "create"; parentPath: string }
  | { mode: "rename"; target: { path: string; name: string } };

export interface FileMoveRequest {
  fileUuids: string[];
  title: string;
}

export interface FileMoveFailureItem {
  fileUuid: string;
  fileName: string;
  reason: string;
}

export interface FileMoveFailure {
  successCount: number;
  failedCount: number;
  targetFolder: string;
  items: FileMoveFailureItem[];
}

export interface FileDeleteFailure {
  successCount: number;
  failedCount: number;
  items: FileMoveFailureItem[];
}

export const FILE_COLUMN_MIN_WIDTHS: Record<string, number> = {
  file_name: 140,
  file_type: 55,
  file_size: 60,
  created_at: 100,
  updated_at: 100,
  file_status: 80,
  actions: 135,
};

// AIDP caps a single batch document removal request at 10 files.
export const AIDP_BATCH_DELETE_MAX = 10;

export const localizedFailureReason = (
  item:
    | {
        reason_zh?: string;
        reason_en?: string;
        message?: string;
        reason?: string;
      }
    | undefined,
  language: string,
  fallback: string
): string =>
  (language.startsWith("zh")
    ? item?.reason_zh || item?.reason_en
    : item?.reason_en || item?.reason_zh) ||
  item?.message ||
  item?.reason ||
  fallback;

export const toDocumentItem = (file: AidpFolderFileItem): AidpDocumentItem => ({
  file_uuid: file.file_uuid || "",
  file_ino_no: "",
  file_name: file.file_name || "",
  file_type: file.file_type,
  file_size: file.file_size,
  updated_at: file.updated_at || undefined,
  status: file.status,
});
