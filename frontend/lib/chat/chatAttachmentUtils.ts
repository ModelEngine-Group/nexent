import type { Dispatch, SetStateAction } from "react";
import { conversationService } from "@/services/conversationService";
import { storageService } from "@/services/storageService";
import { FilePreview } from "@/types/chat";
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
  error?: string;
}> => {
  if (attachments.length === 0) {
    return { uploadedFileUrls: {}, objectNames: {} };
  }

  try {
    const uploadResult = await storageService.uploadFiles(
      attachments.map((attachment) => attachment.file)
    );

    const uploadedFileUrls: Record<string, string> = {};
    const objectNames: Record<string, string> = {};

    if (uploadResult.success_count > 0) {
      uploadResult.results.forEach((result) => {
        if (result.success) {
          uploadedFileUrls[result.file_name] = result.url;
          objectNames[result.file_name] = result.object_name;
        }
      });
    }

    return { uploadedFileUrls, objectNames };
  } catch (error) {
    log.error(t("chatPreprocess.fileUploadFailed"), error);
    return {
      uploadedFileUrls: {},
      objectNames: {},
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
  fileUrls: Record<string, string>
): { type: string; name: string; size: number; url?: string }[] => {
  return attachments.map((attachment) => ({
    type: attachment.type,
    name: attachment.file.name,
    size: attachment.file.size,
    url:
      uploadedFileUrls[attachment.file.name] ||
      (attachment.type === "image"
        ? attachment.previewUrl
        : fileUrls[attachment.id]),
  }));
};

/**
 * Revoke all object URLs created for attachments to free browser memory
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
