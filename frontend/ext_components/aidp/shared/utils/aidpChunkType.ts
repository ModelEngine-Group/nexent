// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

/**
 * AIDP reports chunk content types as TEXT, TABLE and IMAGE. Only TEXT chunks
 * carry an editable text field; TABLE/IMAGE chunks are readable but not
 * editable. The decision is always based on the chunk type AIDP returns, never
 * on the source file's extension or the upload size class.
 */
export const AIDP_EDITABLE_CHUNK_TYPE = "TEXT";

export const normalizeAidpChunkType = (value?: string | null): string =>
  typeof value === "string" ? value.trim().toUpperCase() : "";

export const isAidpChunkEditable = (
  chunk?: { chunk_type?: string } | null
): boolean =>
  normalizeAidpChunkType(chunk?.chunk_type) === AIDP_EDITABLE_CHUNK_TYPE;

/**
 * Derive the AIDP ViewImage file id from a chunk's `file_url`.
 *
 * `file_url` shape is `{kds_id}/{file_ino_no}/{image_uuid}.png`; ViewImage
 * expects `{file_ino_no}_{image_uuid}.png` — drop the knowledge-base prefix
 * and join the rest with `_`. TEXT/TABLE chunks carry the literal "null",
 * which yields no id.
 */
export const deriveAidpImageFileId = (
  fileUrl?: string | null
): string | undefined => {
  if (!fileUrl) return undefined;
  const trimmed = fileUrl.trim();
  if (!trimmed || trimmed.toLowerCase() === "null") return undefined;
  const parts = trimmed.split("/").filter(Boolean);
  if (parts.length < 3) return undefined;
  return parts.slice(1).join("_");
};
