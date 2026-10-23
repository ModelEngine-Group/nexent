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

  const regex =
    /(?:^|;)\s*filename\s*=\s*(?:"((?:\\.|[^"\\\r\n])*)"|([^";\r\n]*))/i;
  const match = regex.exec(contentDisposition);
  // Only double quotes delimit a quoted filename; apostrophes are literal.
  return match?.[1] !== undefined
    ? match[1].replace(/\\(.)/g, "$1")
    : (match?.[2]?.trim() ?? null);
};
