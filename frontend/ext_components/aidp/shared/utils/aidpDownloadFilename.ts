// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { extractFilenameFromContentDisposition } from "@/lib/downloadFilename";
import type { AidpDocumentItem } from "../types/management";

/** AIDP list names may omit the extension supplied separately as file_type. */
export function getAidpDownloadFilename(
  headers: Headers,
  file: Pick<AidpDocumentItem, "file_name" | "file_type">
): string {
  const filename =
    extractFilenameFromContentDisposition(headers.get("Content-Disposition")) ||
    file.file_name.trim() ||
    "download";
  const extension = file.file_type?.trim().replace(/^\./, "");
  if (
    extension &&
    /^[a-z0-9]+$/i.test(extension) &&
    !/\.[^./\\]+$/.test(filename)
  ) {
    return `${filename}.${extension.toLowerCase()}`;
  }
  return filename;
}
