// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

/**
 * Shared upload-center contracts.
 *
 * The floating transfer center, queue and file status machine are independent
 * of any knowledge-base implementation. AIDP and the local ES knowledge base
 * provide an UploadTransport adapter for their own upload API.
 */

export type UploadFileStatus =
  | "queued"
  | "uploading"
  | "success"
  | "validation_failed"
  | "upload_failed"
  | "cancelled";

export interface UploadCapabilities {
  supportsTargetFolder: boolean;
  supportsRelativePaths: boolean;
  maxFilesPerBatch: number;
  maxBytesPerBatch: number;
  maxFilesTotal: number;
  maxBytesTotal: number;
}

export interface UploadContext {
  knowledgeBaseId: string;
  knowledgeBaseName: string;
  /** AIDP-only destination folder; omitted for sources without folders. */
  targetFolder?: string;
  /** UI language for adapter-level failure messages. */
  language?: string;
  /** Optional translator for adapter-level error-code messages. */
  translate?: (key: string, options?: Record<string, unknown>) => string;
}

export interface UploadFileInput {
  file: File;
  /** Path relative to the selected folder; defaults to the file name. */
  relativePath: string;
}

export interface UploadBatchFile {
  id: string;
  file: File;
  relativePath: string;
}

export interface UploadValidationFailure {
  fileId: string;
  reasonKey: string;
  reasonParams?: Record<string, string | number>;
}

export interface UploadValidationResult {
  failures: UploadValidationFailure[];
}

export interface UploadBatchFailure {
  fileId: string;
  reason: string;
  retryable: boolean;
}

export interface UploadBatchResult {
  successFileIds: string[];
  failed: UploadBatchFailure[];
}

export type UploadProgressHandler = (loaded: number, total: number) => void;

export interface UploadTransport {
  capabilities: UploadCapabilities;
  validateFiles(
    files: UploadBatchFile[],
    context: UploadContext
  ): UploadValidationResult;
  uploadBatch(
    files: UploadBatchFile[],
    context: UploadContext,
    signal: AbortSignal,
    onProgress: UploadProgressHandler
  ): Promise<UploadBatchResult>;
}

export interface UploadFileRecord {
  id: string;
  jobId: string;
  file: File;
  name: string;
  size: number;
  relativePath: string;
  context: UploadContext;
  status: UploadFileStatus;
  /** Validation failures use a translatable key; process failures carry text. */
  errorKey?: string;
  errorParams?: Record<string, string | number>;
  error?: string;
  retryable?: boolean;
}

export type UploadBatchStatus =
  "pending" | "uploading" | "success" | "failed" | "cancelled";

export interface UploadBatchRecord {
  id: string;
  jobId: string;
  fileIds: string[];
  status: UploadBatchStatus;
  totalBytes: number;
  loadedBytes: number;
}

export interface UploadJobRecord {
  id: string;
  context: UploadContext;
  sourceLabel: string;
  fileIds: string[];
  batchIds: string[];
  status: "queued" | "uploading" | "completed";
}

export interface UploadCenterSnapshot {
  files: Record<string, UploadFileRecord>;
  fileOrder: string[];
  jobs: Record<string, UploadJobRecord>;
  batches: Record<string, UploadBatchRecord>;
  /** True while active batches are being aborted after a cancel request. */
  cancelling: boolean;
}

export interface UploadEnqueueInput {
  files: UploadFileInput[];
  context: UploadContext;
  transport: UploadTransport;
  sourceLabel: string;
  /** Called once every file in the job reaches a terminal state. */
  onComplete?: () => void;
}
