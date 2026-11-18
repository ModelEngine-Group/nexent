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
