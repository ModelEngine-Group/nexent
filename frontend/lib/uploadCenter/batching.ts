// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type {
  UploadBatchRecord,
  UploadCapabilities,
  UploadFileRecord,
} from "@/types/uploadCenter";

export interface UploadBatchPlan {
  fileIds: string[];
  totalBytes: number;
}

/** Group files by the adapter's per-request count and byte limits. */
export const buildUploadBatches = (
  files: UploadFileRecord[],
  capabilities: UploadCapabilities
): UploadBatchPlan[] => {
  const batches: UploadBatchPlan[] = [];
  let current: UploadFileRecord[] = [];
  let currentBytes = 0;

  const flush = () => {
    if (current.length === 0) return;
    batches.push({
      fileIds: current.map((file) => file.id),
      totalBytes: currentBytes,
    });
    current = [];
    currentBytes = 0;
  };

  for (const file of files) {
    const exceedsCount = current.length >= capabilities.maxFilesPerBatch;
    const exceedsBytes =
      current.length > 0 &&
      currentBytes + file.size > capabilities.maxBytesPerBatch;

    if (exceedsCount || exceedsBytes) flush();

    current.push(file);
    currentBytes += file.size;

    // A single file larger than the normal batch budget gets a solo request;
    // the adapter has already checked the per-file hard limit.
    if (file.size > capabilities.maxBytesPerBatch) flush();
  }

  flush();
  return batches;
};

export interface UploadCenterSummary {
  total: number;
  queued: number;
  uploading: number;
  success: number;
  validationFailed: number;
  uploadFailed: number;
  retryableFailed: number;
  active: number;
  totalBytes: number;
  processedBytes: number;
  percent: number;
  canClose: boolean;
}

export const summarizeUploadFiles = (
  files: Record<string, UploadFileRecord>,
  fileOrder: string[],
  batches: Record<string, UploadBatchRecord>
): UploadCenterSummary => {
  const summary: UploadCenterSummary = {
    total: 0,
    queued: 0,
    uploading: 0,
    success: 0,
    validationFailed: 0,
    uploadFailed: 0,
    retryableFailed: 0,
    active: 0,
    totalBytes: 0,
    processedBytes: 0,
    percent: 0,
    canClose: true,
  };

  for (const id of fileOrder) {
    const file = files[id];
    if (!file) continue;
    summary.total += 1;
    summary.totalBytes += file.size;
    switch (file.status) {
      case "queued":
        summary.queued += 1;
        summary.canClose = false;
        break;
      case "uploading":
        summary.uploading += 1;
        summary.canClose = false;
        break;
      case "success":
        summary.success += 1;
        summary.processedBytes += file.size;
        break;
      case "validation_failed":
        summary.validationFailed += 1;
        summary.processedBytes += file.size;
        break;
      case "upload_failed":
        summary.uploadFailed += 1;
        summary.processedBytes += file.size;
        if (file.retryable !== false) summary.retryableFailed += 1;
        break;
      default:
        break;
    }
  }

  for (const batch of Object.values(batches)) {
    if (batch.status === "uploading") {
      summary.processedBytes += Math.min(
        batch.totalBytes,
        Math.max(0, batch.loadedBytes)
      );
    }
  }

  summary.active = summary.queued + summary.uploading;
  summary.percent =
    summary.totalBytes > 0
      ? Math.min(
          100,
          Math.round((summary.processedBytes / summary.totalBytes) * 100)
        )
      : 0;
  if (summary.total === 0) summary.canClose = false;
  // The XHR reaches 100% when the last byte is sent, but the backend may still
  // be parsing or forwarding the batch. Keep the bar short of 100 until every
  // file has a terminal result so "100%" never coexists with "uploading".
  if (!summary.canClose && summary.total > 0) {
    summary.percent = Math.min(summary.percent, 99);
  }
  return summary;
};

export const formatUploadBytes = (bytes: number): string => {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) {
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
};
