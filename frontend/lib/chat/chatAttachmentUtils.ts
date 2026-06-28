import type { Dispatch, SetStateAction } from "react";
import { conversationService } from "@/services/conversationService";
import { storageService } from "@/services/storageService";
import type { FileAttachment, FilePreview, MinioFileItem } from "@/types/chat";
import log from "@/lib/logger";

/**
 * Handle file upload — create a local object URL for non-image files
 * @returns Generated file ID
 */
export const handleFileUpload = (
  file: File,
  setFileUrls: Dispatch<SetStateAction<Record<string, string>>>,
  t: any
): string => {
  const fileId = `file-${Date.now()}-${Math.random()
    .toString(36)
    .substring(7)}`;

  if (!file.type.startsWith("image/")) {
    const fileUrl = URL.createObjectURL(file);
    setFileUrls((prev) => ({ ...prev, [fileId]: fileUrl }));
  }

  return fileId;
};

/**
 * Handle image upload (reserved for future use)
 */
export const handleImageUpload = (file: File, t: any): void => {};

/**
 * Upload attachments to storage service
 * @returns Uploaded file URLs and object names
 */
export const uploadAttachments = async (
  attachments: FilePreview[],
  t: any
): Promise<{
  uploadedFileUrls: Record<string, string>;
  objectNames: Record<string, string>;
  presignedUrls: Record<string, string>;
  error?: string;
}> => {
  if (attachments.length === 0) {
    return { uploadedFileUrls: {}, objectNames: {}, presignedUrls: {} };
  }

  try {
    const uploadResult = await storageService.uploadFiles(
      attachments.map((attachment) => attachment.file)
    );

    const uploadedFileUrls: Record<string, string> = {};
    const objectNames: Record<string, string> = {};
    const presignedUrls: Record<string, string> = {};

    if (uploadResult.success_count > 0) {
      uploadResult.results.forEach((result) => {
        if (result.success) {
          uploadedFileUrls[result.file_name] = result.url;
          objectNames[result.file_name] = result.object_name;
          // Store presigned URL for external MCP tool access
          if (result.presigned_url) {
            presignedUrls[result.file_name] = result.presigned_url;
          }
        }
      });
    }

    const failedResults = uploadResult.results.filter((result) => !result.success);
    if (failedResults.length > 0 || uploadResult.success_count < attachments.length) {
      const failedMessage = failedResults
        .map((result) => `${result.file_name || "file"}: ${result.error || "Upload failed"}`)
        .join("; ");
      return {
        uploadedFileUrls,
        objectNames,
        presignedUrls,
        error: failedMessage || "Upload failed",
      };
    }

    return { uploadedFileUrls, objectNames, presignedUrls };
  } catch (error) {
    log.error(t("chatPreprocess.fileUploadFailed"), error);
    return {
      uploadedFileUrls: {},
      objectNames: {},
      presignedUrls: {},
      error: error instanceof Error ? error.message : String(error),
    };
  }
};

/**
 * Build attachment metadata objects for a chat message
 */
export const createMessageAttachments = (
  attachments: FilePreview[],
  uploadedFileUrls: Record<string, string>,
  fileUrls: Record<string, string>,
  objectNames?: Record<string, string>,
  presignedUrls?: Record<string, string>
): FileAttachment[] => {
  return attachments.map((attachment) => ({
    type: attachment.type,
    name: attachment.file.name,
    size: attachment.file.size,
    url:
      uploadedFileUrls[attachment.file.name] ||
      (attachment.type === "image"
        ? attachment.previewUrl
        : fileUrls[attachment.id]),
    object_name: objectNames?.[attachment.file.name],
    presigned_url: presignedUrls?.[attachment.file.name],
  }));
};

/**
 * Build the complete attachment payload for an agent run request.
 *
 * Orchestrates the full attachment pipeline used by chat/debug/compare send paths:
 * upload → validate → build message attachments → (optionally) preprocess for
 * descriptions → assemble the `minio_files` array. Centralizing this here removes
 * duplicated upload/mapping logic across debug and compare send handlers and
 * guarantees both paths apply the same "missing upload" validation.
 *
 * @param attachments     - Selected file previews (images and/or documents) to send.
 * @param fileUrls        - Local object URLs keyed by attachment id (non-image files).
 * @param question        - The user's question text; passed to preprocessing.
 * @param signal          - AbortSignal for cancellation; required when `withDescription` is true.
 * @param withDescription - If true, run `preprocessAttachments` to fetch per-file
 *                          descriptions and fill `minio_files[].description`. Debug mode
 *                          sets this true; compare mode sets it false (descriptions stay "").
 * @param t               - i18n translation function (passed through to upload/preprocess).
 * @returns `{ messageAttachments, minioFiles }` on success (both empty arrays when there
 *          are no attachments). On failure returns `{ messageAttachments: [], minioFiles: [], error }`
 *          where `error` is a localized/concatenated reason string; the caller is responsible
 *          for surfacing it to the user.
 */
export const buildMinioFilePayload = async (
  attachments: FilePreview[],
  fileUrls: Record<string, string>,
  question: string,
  signal: AbortSignal | undefined,
  withDescription: boolean,
  t: any
): Promise<{
  messageAttachments: FileAttachment[];
  minioFiles: MinioFileItem[];
  error?: string;
}> => {
  // No attachments: return empty payload, caller decides whether to omit the field.
  if (attachments.length === 0) {
    return { messageAttachments: [], minioFiles: [] };
  }

  // 1. Upload all attachments to storage (MinIO).
  const uploadResult = await uploadAttachments(attachments, t);
  if (uploadResult.error) {
    return { messageAttachments: [], minioFiles: [], error: uploadResult.error };
  }
  const { uploadedFileUrls, objectNames, presignedUrls } = uploadResult;

  // 2. Guard: every attachment must have both a public URL and an object name.
  const missing = attachments.filter(
    (attachment) =>
      !uploadedFileUrls[attachment.file.name] ||
      !objectNames[attachment.file.name]
  );
  if (missing.length > 0) {
    return {
      messageAttachments: [],
      minioFiles: [],
      error: missing.map((attachment) => attachment.file.name).join(", "),
    };
  }

  // 3. Build the message-side attachment metadata (for local UI rendering).
  const messageAttachments = createMessageAttachments(
    attachments,
    uploadedFileUrls,
    fileUrls,
    objectNames,
    presignedUrls
  );

  // 4. Optionally fetch per-file descriptions (currently a no-op in preprocessAttachments).
  let descriptions: Record<string, string> = {};
  if (withDescription && signal) {
    const preprocessResult = await preprocessAttachments(
      question,
      attachments,
      signal,
      () => {},
      t,
      -1
    );
    descriptions = preprocessResult.fileDescriptions || {};
  }

  // 5. Assemble the `minio_files` payload sent to the backend agent run.
  const minioFiles: MinioFileItem[] = messageAttachments.map((attachment) => ({
    object_name: objectNames[attachment.name] || "",
    name: attachment.name,
    type: attachment.type,
    size: attachment.size,
    url: uploadedFileUrls[attachment.name] || attachment.url,
    presigned_url: presignedUrls[attachment.name] || "",
    description: descriptions[attachment.name] || "",
  }));

  return { messageAttachments, minioFiles };
};

/**
 * Revoke all object URLs created for attachments to free browser memory.
 *
 * @param attachments - Attachments whose `previewUrl` (image) object URLs should be revoked.
 * @param fileUrls    - Map of attachment id → local object URL (non-image files) to revoke.
 */
export const cleanupAttachmentUrls = (
  attachments: FilePreview[],
  fileUrls: Record<string, string>
): void => {
  attachments.forEach((attachment) => {
    if (attachment.previewUrl) {
      URL.revokeObjectURL(attachment.previewUrl);
    }
  });

  Object.values(fileUrls).forEach((url) => {
    URL.revokeObjectURL(url);
  });
};

/**
 * Preprocess attachment files before sending (currently a no-op, kept for future use)
 * @returns Preprocessed query and processing status
 */
export const preprocessAttachments = async (
  content: string,
  attachments: FilePreview[],
  signal: AbortSignal,
  onProgress: (data: any) => void,
  t: any,
  conversationId?: number
): Promise<{
  finalQuery: string;
  success: boolean;
  error?: string;
  fileDescriptions?: Record<string, string>;
}> => {
  if (attachments.length === 0) {
    return { finalQuery: content, success: true };
  }

  // Preprocessing is currently disabled — return the original content unchanged.
  // To re-enable, implement the streaming call to conversationService.preprocessFiles here.
  return { finalQuery: content, success: true };
};
