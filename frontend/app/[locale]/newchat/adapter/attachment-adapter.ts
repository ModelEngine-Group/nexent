"use client";

import type {
  Attachment,
  AttachmentAdapter,
  CompleteAttachment,
  PendingAttachment,
  ThreadUserMessagePart,
} from "@assistant-ui/core";
import { storageService } from "@/services/storageService";
import log from "@/lib/logger";
import { getAttachmentType } from "../utils/attachment-type";

// assistant-ui's `fileMatchesAccept` treats "*" as a special wildcard that
// matches every file. Note that "*/*" is NOT a valid wildcard here — the
// matcher only recognises the literal "*" or concrete MIME strings, so
// "*/*" would reject all files.
const ACCEPT_STRING = "*";
const UPLOAD_FOLDER = "attachments";

/**
 * MinIO upload metadata carried on the attachment so the ChatModelAdapter can
 * forward it to the backend in `minio_files`. The shape matches `MinioFileItem`
 * from `types/chat.ts`.
 */
interface UploadedFileMeta {
  object_name: string;
  url: string;
  presigned_url?: string;
  type: string;
  size: number;
}

export const compositeAttachmentAdapter: AttachmentAdapter = {
  accept: ACCEPT_STRING,

  async add({ file }: { file: File }): Promise<PendingAttachment> {
    const id = `att-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const type = getAttachmentType(file);

    return {
      id,
      status: { type: "running", reason: "uploading", progress: 0 },
      type,
      name: file.name,
      contentType: file.type,
      file,
      content: [],
    };
  },

  async remove(_attachment: Attachment): Promise<void> {
    log.log("[AttachmentAdapter] Remove attachment");
  },

  async send(attachment: PendingAttachment): Promise<CompleteAttachment> {
    const file = attachment.file;
    log.log(
      "[AttachmentAdapter] Uploading file to MinIO:",
      file.name,
      "type:",
      attachment.type,
    );

    try {
      console.log(file)
      const result = await storageService.uploadFiles([file], UPLOAD_FOLDER);
      const item = result.results?.find((r) => r.success);

      if (!result.success_count || !item) {
        const errorMessage =
          result.results?.find((r) => !r.success)?.error ||
          "Upload failed: no successful result returned";
        log.error("[AttachmentAdapter] Upload failed:", errorMessage);
        throw new Error(errorMessage);
      }

      // Prefer the presigned URL (works for time-limited access); fall back to url.
      const serverUrl = item.presigned_url || item.url;
      const isImage = attachment.type === "image";

      // Build the content part so the message attachment carries a usable
      // reference for both UI rendering and downstream consumption.
      const part: ThreadUserMessagePart = isImage
        ? { type: "image", image: serverUrl }
        : { type: "file", filename: file.name, data: serverUrl, mimeType: file.type || "application/octet-stream" };

      // Stash upload metadata on the attachment for the ChatModelAdapter to
      // forward as `minio_files`. Cast through unknown because the public
      // BaseAttachment type does not declare these fields.
      const meta: UploadedFileMeta = {
        object_name: item.object_name,
        url: serverUrl,
        presigned_url: item.presigned_url,
        type: file.type || attachment.type,
        size: item.file_size ?? file.size,
      };

      const completeAttachment: CompleteAttachment = {
        id: attachment.id,
        status: { type: "complete" },
        type: attachment.type as "image" | "document" | "file",
        name: attachment.name,
        contentType: attachment.contentType,
        content: [part],
        // Carry upload metadata alongside the typed fields.
        ...(meta as object),
      };
      console.log(completeAttachment)
      return completeAttachment;
    } catch (error) {
      log.error("[AttachmentAdapter] Upload error:", error);
      // Surface the error to the assistant-ui runtime so the user sees it.
      throw error instanceof Error
        ? error
        : new Error("Failed to upload attachment");
    }
  },
};
