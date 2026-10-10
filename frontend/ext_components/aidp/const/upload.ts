export const AIDP_FILE_EXTENSIONS = {
  TEXT: ["txt", "json", "md", "markdown"] as const,
  WEB: ["html"] as const,
  DOCUMENT: ["pdf", "docx", "doc", "ppt", "pptx"] as const,
  SPREADSHEET: ["xlsx", "xls", "csv"] as const,
  IMAGE: ["png", "jpeg", "jpg", "bmp"] as const,
} as const;

// Flat array of all allowed AIDP extensions (lowercase, no dot)
export const AIDP_ALLOWED_EXTENSIONS = [
  ...AIDP_FILE_EXTENSIONS.TEXT,
  ...AIDP_FILE_EXTENSIONS.WEB,
  ...AIDP_FILE_EXTENSIONS.DOCUMENT,
  ...AIDP_FILE_EXTENSIONS.SPREADSHEET,
  ...AIDP_FILE_EXTENSIONS.IMAGE,
] as const;

// MIME types accepted by AIDP
export const AIDP_ALLOWED_MIME_TYPES = new Set<string>([
  "text/plain",
  "application/json",
  "text/markdown",
  "text/html",
  "application/pdf",
  "application/msword",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "application/vnd.ms-powerpoint",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  "application/vnd.ms-excel",
  "text/csv",
  "application/csv",
  "image/png",
  "image/jpeg",
  "image/bmp",
]);

// Dragger `accept` prop value (comma-separated dot-extensions)
export const AIDP_ACCEPT_STRING = [
  ...AIDP_FILE_EXTENSIONS.TEXT,
  ...AIDP_FILE_EXTENSIONS.WEB,
  ...AIDP_FILE_EXTENSIONS.DOCUMENT,
  ...AIDP_FILE_EXTENSIONS.SPREADSHEET,
  ...AIDP_FILE_EXTENSIONS.IMAGE,
]
  .map((ext) => `.${ext}`)
  .join(",");

export const AIDP_MAX_UPLOAD_FILE_COUNT = 50;
export const AIDP_SMALL_FILE_MAX_SIZE_MB = 20;
export const AIDP_OTHER_FILE_MAX_SIZE_MB = 1024;
export const AIDP_SMALL_FILE_EXTENSIONS = [
  "txt",
  "json",
  "md",
  "html",
  "xls",
  "xlsx",
  "csv",
] as const;
export const AIDP_SMALL_FILE_MAX_SIZE_BYTES =
  AIDP_SMALL_FILE_MAX_SIZE_MB * 1024 * 1024;
export const AIDP_OTHER_FILE_MAX_SIZE_BYTES =
  AIDP_OTHER_FILE_MAX_SIZE_MB * 1024 * 1024;
