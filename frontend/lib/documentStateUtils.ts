// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { Document } from "@/types/knowledgeBase";

const DOCUMENT_STATE_FIELDS = [
  "id",
  "kb_id",
  "name",
  "type",
  "size",
  "create_time",
  "chunk_num",
  "token_num",
  "status",
  "latest_task_id",
  "file_id",
  "error_code",
  "error_reason",
  "error_stage",
  "failed_at",
  "processed_chunk_num",
  "total_chunk_num",
] as const satisfies readonly (keyof Document)[];

const areNullableValuesEqual = (left: unknown, right: unknown): boolean =>
  (left == null && right == null) || Object.is(left, right);

const TAG_FIELDS = [
  "definition_id",
  "definition_key",
  "definition_name",
  "selection_mode",
  "value_id",
  "display_value",
  "value_status",
] as const;

/**
 * Compare tag assignments by content. Polling responses rebuild the arrays and
 * objects, so identity comparison would either hide real tag changes or force
 * a re-render on every poll.
 */
const areTagsEqual = (
  current: Document["tags"],
  next: Document["tags"]
): boolean => {
  const currentTags = current ?? [];
  const nextTags = next ?? [];
  if (currentTags.length !== nextTags.length) return false;

  return currentTags.every((currentTag, index) => {
    const nextTag = nextTags[index];
    return TAG_FIELDS.every((field) =>
      Object.is(currentTag[field], nextTag[field])
    );
  });
};

/**
 * Compare document data that comes from the server while ignoring the local
 * selection flag. Polling returns new object instances even when no document
 * data changed, so this prevents redundant context updates and renders.
 */
export const areDocumentsEqual = (
  current: readonly Document[] | undefined,
  next: readonly Document[]
): boolean => {
  if (!current || current.length !== next.length) return false;

  return current.every((currentDocument, index) => {
    const nextDocument = next[index];
    return (
      DOCUMENT_STATE_FIELDS.every((field) =>
        areNullableValuesEqual(currentDocument[field], nextDocument[field])
      ) && areTagsEqual(currentDocument.tags, nextDocument.tags)
    );
  });
};
