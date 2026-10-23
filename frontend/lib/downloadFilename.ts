// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

/** Extract RFC 5987 UTF-8, quoted or unquoted attachment filenames. */
export const extractFilenameFromContentDisposition = (
  contentDisposition: string | null
): string | null => {
  if (!contentDisposition) {
    return null;
  }

  const utf8Regex = /filename\*=UTF-8''([^;]+)/i;
  const utf8Match = utf8Regex.exec(contentDisposition);
  if (utf8Match?.[1]) {
    try {
      return decodeURIComponent(utf8Match[1].trim());
    } catch {
      // Fall back to plain filename parsing on invalid encoding.
    }
  }

  const regex = /filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/;
  const match = regex.exec(contentDisposition);
  return match?.[1]?.replace(/['"]/g, "").trim() ?? null;
};
