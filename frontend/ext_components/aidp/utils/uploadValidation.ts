import {
  AIDP_ALLOWED_EXTENSIONS,
  AIDP_ALLOWED_MIME_TYPES,
  AIDP_MAX_UPLOAD_FILE_COUNT,
  AIDP_OTHER_FILE_MAX_SIZE_BYTES,
  AIDP_OTHER_FILE_MAX_SIZE_MB,
  AIDP_SMALL_FILE_EXTENSIONS,
  AIDP_SMALL_FILE_MAX_SIZE_BYTES,
  AIDP_SMALL_FILE_MAX_SIZE_MB,
} from "../const/upload";

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
