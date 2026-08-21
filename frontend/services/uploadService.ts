import { TFunction } from "i18next";

import { NAME_CHECK_STATUS } from "@/const/agentConfig";
import {
  AIDP_ALLOWED_EXTENSIONS,
  AIDP_ALLOWED_MIME_TYPES,
  AIDP_MAX_UPLOAD_FILE_COUNT,
  AIDP_OTHER_FILE_MAX_SIZE_BYTES,
  AIDP_OTHER_FILE_MAX_SIZE_MB,
  AIDP_SMALL_FILE_EXTENSIONS,
  AIDP_SMALL_FILE_MAX_SIZE_BYTES,
  AIDP_SMALL_FILE_MAX_SIZE_MB,
  KNOWLEDGE_BASE_MAX_FILE_SIZE_BYTES,
  KNOWLEDGE_BASE_MAX_FILE_SIZE_MB,
} from "@/const/knowledgeBase";
import knowledgeBaseService from "@/services/knowledgeBaseService";
import { AbortableError } from "@/types/knowledgeBase";
import log from "@/lib/logger";

import "../app/[locale]/i18n";

// New method to check knowledge base name status
export const checkKnowledgeBaseName = async (
  knowledgeBaseName: string,
  t: TFunction
): Promise<{ status: string; action?: string }> => {
  try {
    // Call new service method
    return await knowledgeBaseService.checkKnowledgeBaseName(knowledgeBaseName);
  } catch (error) {
    log.error(t("knowledgeBase.check.nameError"), error);
    // Return a status indicating check failure
    return { status: NAME_CHECK_STATUS.CHECK_FAILED };
  }
};

// Get knowledge base document information
export const fetchKnowledgeBaseInfo = async (
  indexName: string,
  abortController: AbortController,
  currentKnowledgeBaseRef: React.MutableRefObject<string>,
  onSuccess: () => void,
  onError: (error: unknown) => void,
  t: TFunction,
  message: any
) => {
  try {
    if (
      !abortController.signal.aborted &&
      indexName === currentKnowledgeBaseRef.current
    ) {
      onSuccess();
    }
  } catch (error: unknown) {
    const err = error as AbortableError;
    if (
      err.name !== "AbortError" &&
      indexName === currentKnowledgeBaseRef.current
    ) {
      log.error(t("knowledgeBase.fetch.error"), error);
      message.error(t("knowledgeBase.fetch.retryError"));
      onError(error);
    }
  }
};

// File type validation
export const validateFileType = (
  file: File,
  t: TFunction,
  message: any
): boolean => {
  const validTypes = [
    "application/pdf",
    "application/msword", // .doc
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document", // .docx
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/markdown",
    "text/plain",
    "text/csv",
    "application/csv",
    "application/epub",
    "application/epub+zip",
    "text/html",
    "application/json",
    "application/xml",
    "text/xml",
  ];

  // First check MIME type
  let isValidType = validTypes.includes(file.type);

  // If MIME type is empty or not in the list, check by file extension
  if (!isValidType) {
    const name = file.name.toLowerCase();
    if (
      name.endsWith(".md") ||
      name.endsWith(".markdown") ||
      name.endsWith(".csv") ||
      name.endsWith(".doc") ||
      name.endsWith(".docx")
    ) {
      isValidType = true;
    }
  }

  if (!isValidType) {
    message.error(t("knowledgeBase.upload.invalidFileType"));
    return false;
  }

  return true;
};

export const isKnowledgeBaseFileSizeValid = (file: File): boolean =>
  file.size <= KNOWLEDGE_BASE_MAX_FILE_SIZE_BYTES;

export const validateKnowledgeBaseFileSize = (
  file: File,
  t: TFunction,
  message: any
): boolean => {
  if (isKnowledgeBaseFileSizeValid(file)) {
    return true;
  }

  message.error(
    t("knowledgeBase.upload.fileTooLarge", {
      limit: KNOWLEDGE_BASE_MAX_FILE_SIZE_MB,
    })
  );
  return false;
};

/**
 * Pure check (no side effects): returns true if the file's MIME type or extension is allowed for AIDP.
 */
export const isAidpFileValid = (file: File): boolean => {
  if (file.type && AIDP_ALLOWED_MIME_TYPES.has(file.type)) return true;
  const ext = file.name.toLowerCase().split(".").pop() ?? "";
  return (AIDP_ALLOWED_EXTENSIONS as readonly string[]).includes(ext);
};

export interface AidpFileValidationResult {
  valid: File[];
  invalidType: File[];
  oversized: Array<{ file: File; maxSizeMb: number }>;
  exceededCount: File[];
}

const getAidpFileSizeLimit = (file: File) => {
  const extension = file.name.toLowerCase().split(".").pop() ?? "";
  const isSmallFile = (
    AIDP_SMALL_FILE_EXTENSIONS as readonly string[]
  ).includes(extension);
  return isSmallFile
    ? {
        bytes: AIDP_SMALL_FILE_MAX_SIZE_BYTES,
        megabytes: AIDP_SMALL_FILE_MAX_SIZE_MB,
      }
    : {
        bytes: AIDP_OTHER_FILE_MAX_SIZE_BYTES,
        megabytes: AIDP_OTHER_FILE_MAX_SIZE_MB,
      };
};

export const validateAidpFiles = (
  files: File[],
  currentFileCount = 0
): AidpFileValidationResult => {
  const exceedsCount =
    currentFileCount + files.length > AIDP_MAX_UPLOAD_FILE_COUNT;
  const withinCount = exceedsCount ? [] : files;
  const exceededCount = exceedsCount ? files : [];
  const valid: File[] = [];
  const invalidType: File[] = [];
  const oversized: Array<{ file: File; maxSizeMb: number }> = [];

  for (const file of withinCount) {
    if (!isAidpFileValid(file)) {
      invalidType.push(file);
      continue;
    }
    const limit = getAidpFileSizeLimit(file);
    if (file.size > limit.bytes) {
      oversized.push({ file, maxSizeMb: limit.megabytes });
      continue;
    }
    valid.push(file);
  }

  return { valid, invalidType, oversized, exceededCount };
};

/**
 * Split a batch of files into valid/invalid subsets. Shows a single error toast
 * when any file is invalid (aligned with antd's beforeUpload batch semantics).
 */
export const partitionAidpFiles = (
  files: File[],
  t: TFunction,
  message: any,
  currentFileCount = 0
): AidpFileValidationResult => {
  const result = validateAidpFiles(files, currentFileCount);
  if (result.invalidType.length > 0) {
    message.error(
      t("aidpKnowledge.invalidFileType", { count: result.invalidType.length })
    );
  }
  if (result.oversized.length > 0) {
    message.error(
      result.oversized
        .map(({ file, maxSizeMb }) =>
          t("aidpKnowledge.fileTooLarge", {
            fileName: file.name,
            maxSize: maxSizeMb,
          })
        )
        .join("; ")
    );
  }
  if (result.exceededCount.length > 0) {
    message.error(
      t("aidpKnowledge.tooManyFiles", {
        count: currentFileCount + files.length,
        maxCount: AIDP_MAX_UPLOAD_FILE_COUNT,
      })
    );
  }
  return result;
};
