// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import {
  AIDP_ALLOWED_EXTENSIONS,
  AIDP_SMALL_FILE_EXTENSIONS,
  AIDP_SMALL_FILE_MAX_SIZE_BYTES,
  AIDP_OTHER_FILE_MAX_SIZE_BYTES,
} from "@/ext_components/aidp/features/file-import/uploadConstants";
import aidpKnowledgeService from "@/ext_components/aidp/shared/services/aidpKnowledgeService";
import { getAidpUploadErrorMessage } from "@/ext_components/aidp/shared/services/aidpUploadUtils";
import type { AidpUploadFailedItem } from "@/ext_components/aidp/shared/types/management";
import type {
  UploadBatchFile,
  UploadBatchResult,
  UploadCapabilities,
  UploadContext,
  UploadTransport,
  UploadValidationFailure,
  UploadValidationResult,
} from "@/types/uploadCenter";

export const AIDP_UPLOAD_CAPABILITIES: UploadCapabilities = {
  supportsTargetFolder: true,
  supportsRelativePaths: true,
  maxFilesPerBatch: 50,
  maxBytesPerBatch: 512 * 1024 * 1024,
  maxFilesTotal: 1000,
  maxBytesTotal: 10 * 1024 * 1024 * 1024,
};

const failure = (
  fileId: string,
  reasonKey: string,
  reasonParams?: Record<string, string | number>
): UploadValidationFailure => ({ fileId, reasonKey, reasonParams });

const extensionOf = (name: string): string =>
  name.toLowerCase().split(".").pop() ?? "";

const maxBytesFor = (file: File): number =>
  (AIDP_SMALL_FILE_EXTENSIONS as readonly string[]).includes(
    extensionOf(file.name)
  )
    ? AIDP_SMALL_FILE_MAX_SIZE_BYTES
    : AIDP_OTHER_FILE_MAX_SIZE_BYTES;

const validateFiles = (
  files: UploadBatchFile[],
  context: UploadContext
): UploadValidationResult => {
  void context;
  const failures: UploadValidationFailure[] = [];
  const totalBytes = files.reduce((sum, file) => sum + file.file.size, 0);

  if (files.length > AIDP_UPLOAD_CAPABILITIES.maxFilesTotal) {
    return {
      failures: files.map((file) =>
        failure(file.id, "uploadCenter.validation.tooManyFiles", {
          max: AIDP_UPLOAD_CAPABILITIES.maxFilesTotal,
        })
      ),
    };
  }
  if (totalBytes > AIDP_UPLOAD_CAPABILITIES.maxBytesTotal) {
    return {
      failures: files.map((file) =>
        failure(file.id, "uploadCenter.validation.tooManyBytes", {
          max: Math.round(
            AIDP_UPLOAD_CAPABILITIES.maxBytesTotal / (1024 * 1024 * 1024)
          ),
        })
      ),
    };
  }

  const seenNames = new Set<string>();
  for (const file of files) {
    const extension = extensionOf(file.file.name);
    if (!(AIDP_ALLOWED_EXTENSIONS as readonly string[]).includes(extension)) {
      failures.push(
        failure(file.id, "uploadCenter.validation.invalidType", {
          fileName: file.file.name,
        })
      );
      continue;
    }
    const maxBytes = maxBytesFor(file.file);
    if (file.file.size > maxBytes) {
      failures.push(
        failure(file.id, "uploadCenter.validation.fileTooLarge", {
          fileName: file.file.name,
          maxSize: maxBytes / (1024 * 1024),
        })
      );
      continue;
    }
    if (seenNames.has(file.file.name)) {
      failures.push(
        failure(file.id, "uploadCenter.validation.duplicateFile", {
          fileName: file.file.name,
        })
      );
      continue;
    }
    seenNames.add(file.file.name);
  }
  return { failures };
};

const reasonForFailure = (
  item: AidpUploadFailedItem | undefined,
  language?: string
): string => {
  if (!item) return "uploadCenter.error.unknown";
  return language?.startsWith("zh")
    ? item.reason_zh || item.reason_en || "uploadCenter.error.unknown"
    : item.reason_en || item.reason_zh || "uploadCenter.error.unknown";
};

const uploadBatch = async (
  files: UploadBatchFile[],
  context: UploadContext,
  signal: AbortSignal,
  onProgress: (loaded: number, total: number) => void
): Promise<UploadBatchResult> => {
  const byName = new Map(files.map((file) => [file.file.name, file.id]));
  let response;
  try {
    response = await aidpKnowledgeService.uploadDocsWithProgress(
      context.knowledgeBaseId,
      files.map((file) => file.file),
      onProgress,
      signal,
      {
        targetFolder: context.targetFolder ?? "/",
        relativePaths: files.map((file) => file.relativePath),
      }
    );
  } catch (error) {
    if (signal.aborted) throw error;
    const reason = getAidpUploadErrorMessage(
      error,
      context.translate ?? ((key) => key),
      "uploadCenter.error.unknown"
    );
    return {
      successFileIds: [],
      failed: files.map((file) => ({
        fileId: file.id,
        reason,
        retryable: true,
      })),
    };
  }

  const successFileIds: string[] = [];
  const failed: UploadBatchResult["failed"] = [];
  const handled = new Set<string>();

  for (const item of response.success_list ?? []) {
    const fileId = byName.get(item.file_name);
    if (fileId) {
      successFileIds.push(fileId);
      handled.add(fileId);
    }
  }
  for (const item of response.failed_list ?? []) {
    const fileId = byName.get(item.file_name);
    if (!fileId) continue;
    failed.push({
      fileId,
      reason: reasonForFailure(item, context.language),
      retryable: true,
    });
    handled.add(fileId);
  }
  for (const file of files) {
    if (handled.has(file.id)) continue;
    failed.push({
      fileId: file.id,
      reason: "uploadCenter.error.unknown",
      retryable: true,
    });
  }

  return { successFileIds, failed };
};

export const aidpUploadTransport: UploadTransport = {
  capabilities: AIDP_UPLOAD_CAPABILITIES,
  validateFiles,
  uploadBatch,
};
