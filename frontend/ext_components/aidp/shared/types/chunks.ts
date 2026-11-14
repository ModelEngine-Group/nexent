// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

/**
 * One AIDP semantic chunk of an ingested file.
 *
 * Every field except `chunk_id` is optional because AIDP may omit data for a
 * given chunk; the UI shows an empty state instead of inventing content.
 */
export interface AidpChunk {
  /** AIDP chunk identifier; detail, edit and delete all address the chunk by it. */
  chunk_id: number;
  chunk_text?: string;
  /** AIDP chunk type: text, table, image, caption or multimodal. */
  chunk_type?: string;
  file_name?: string;
  file_url?: string;
  /** Source page numbers; the contract exposes no in-page coordinates. */
  page_ids?: number[];
  /** Read-only custom metadata configured on the AIDP side. */
  metadata?: Record<string, unknown>;
  /** Only present when AIDP returns it; otherwise the detail shows "—". */
  updated_at?: string;
}

export interface AidpChunkListResponse {
  value: AidpChunk[];
  total_count: number;
  has_more: boolean;
  /** False when AIDP did not report a global total and it was derived. */
  total_reliable: boolean;
}

/** Body for adding a chunk: the contract accepts only these two fields. */
export interface AidpChunkCreatePayload {
  file_uuid: string;
  chunk_text: string;
}

/** Body for updating a chunk: text is the only writable field. */
export interface AidpChunkUpdatePayload {
  chunk_text: string;
}

/** AIDP answers a chunk creation with the new identifier. */
export interface AidpChunkCreateResponse {
  chunk_id?: number | string;
}
