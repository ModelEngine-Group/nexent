// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

/**
 * Internal file-move drag contract.
 *
 * The directory tree also accepts operating-system file drops for upload, so
 * an internal move must be distinguishable from an external `Files` drag.
 * A custom MIME type carries the selected file UUIDs without looking like an
 * upload.
 */
export const AIDP_FILE_MOVE_MIME = "application/x-nexent-aidp-file-move";

export interface AidpFileMoveDragPayload {
  fileUuids: string[];
}

export const hasAidpFileMoveDrag = (
  dataTransfer: DataTransfer | null | undefined
): boolean =>
  Boolean(
    dataTransfer && Array.from(dataTransfer.types).includes(AIDP_FILE_MOVE_MIME)
  );

export const writeAidpFileMoveDrag = (
  dataTransfer: DataTransfer,
  fileUuids: string[]
): void => {
  const payload: AidpFileMoveDragPayload = { fileUuids };
  dataTransfer.setData(AIDP_FILE_MOVE_MIME, JSON.stringify(payload));
  dataTransfer.setData("text/plain", `${fileUuids.length}`);
  dataTransfer.effectAllowed = "move";
};

export const readAidpFileMoveDrag = (
  dataTransfer: DataTransfer | null | undefined
): string[] => {
  if (!dataTransfer) return [];
  const raw = dataTransfer.getData(AIDP_FILE_MOVE_MIME);
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw) as AidpFileMoveDragPayload;
    return Array.isArray(parsed.fileUuids)
      ? parsed.fileUuids.filter(
          (uuid): uuid is string => typeof uuid === "string" && Boolean(uuid)
        )
      : [];
  } catch {
    return [];
  }
};
