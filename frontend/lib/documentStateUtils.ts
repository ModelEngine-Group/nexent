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
    return DOCUMENT_STATE_FIELDS.every((field) =>
      areNullableValuesEqual(currentDocument[field], nextDocument[field])
    );
  });
};
