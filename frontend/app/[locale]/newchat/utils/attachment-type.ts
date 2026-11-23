/**
 * Coarse-grained attachment type shared by the attachment adapter and the UI
 * layer. The values map onto assistant-ui's `BaseAttachment.type` field and
 * ultimately onto the `minio_files[i].type` payload sent to the backend:
 *
 * - `image`: visual content the LLM can consume as a multimodal image.
 * - `document`: parseable text/structured content (PDF, Word, spreadsheet,
 *   presentation, JSON, plain text).
 * - `file`: everything else (archives, audio, video, code, unknown).
 *
 * This is intentionally a 3-way coarse split. Fine-grained discrimination
 * (e.g. PDF vs DOCX) belongs to the raw MIME in `contentType`.
 */

export type AttachmentType = "image" | "document" | "file";

/**
 * Classify a browser `File` into one of the supported types.
 *
 * The order of the checks matters: `image/` must come first because some
 * browsers report generic types for image files. `application/json` is
 * classified as `document` because LLMs typically consume it as data.
 */
export const getAttachmentType = (file: File): AttachmentType => {
  if (file.type.startsWith("image/")) return "image";
  if (
    file.type.startsWith("text/") ||
    file.type === "application/pdf" ||
    file.type.includes("word") ||
    file.type.includes("spreadsheet") ||
    file.type.includes("presentation") ||
    file.type === "application/json"
  ) {
    return "document";
  }
  return "file";
};