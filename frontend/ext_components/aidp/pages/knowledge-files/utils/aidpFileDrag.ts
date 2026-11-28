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

/**
 * Replace the browser's default row snapshot with a compact label containing
 * only the dragged file name(s). The default snapshot includes every table
 * column (type, size, timestamps), which reads like a data row rather than the
 * file being moved.
 */
export const setAidpFileMoveDragImage = (
  dataTransfer: DataTransfer,
  label: string
): void => {
  if (!label || typeof document === "undefined") return;
  document
    .querySelectorAll("[data-aidp-drag-preview]")
    .forEach((element) => element.remove());
  const preview = document.createElement("div");
  preview.textContent = label;
  preview.setAttribute("data-aidp-drag-preview", "true");
  Object.assign(preview.style, {
    position: "fixed",
    top: "-1000px",
    left: "-1000px",
    maxWidth: "320px",
    overflow: "hidden",
    padding: "6px 10px",
    border: "1px solid #d9d9d9",
    borderRadius: "6px",
    background: "#ffffff",
    boxShadow: "0 4px 12px rgba(0, 0, 0, 0.12)",
    color: "#1f1f1f",
    font: "13px/20px sans-serif",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
    pointerEvents: "none",
  });
  document.body.appendChild(preview);
  dataTransfer.setDragImage(preview, 10, 10);
  window.setTimeout(() => preview.remove(), 0);
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
