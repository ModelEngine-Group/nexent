/** MinIO metadata retained on chat attachments after upload or history reload. */
interface AttachmentMetadata {
  name?: string;
  contentType?: string;
  type?: string;
  object_name?: string;
  url?: string;
  presigned_url?: string;
  size?: number;
}

export interface MinioFilePayload {
  name: string;
  object_name: string;
  type: string;
  size: number;
  url: string;
  presigned_url?: string;
}

export function extractMinioFiles(
  message: { attachments?: unknown } | undefined,
  onMissingObjectName?: (name: string) => void
): MinioFilePayload[] {
  if (!message || !Array.isArray(message.attachments)) return [];

  const files: MinioFilePayload[] = [];
  for (const attachment of message.attachments as AttachmentMetadata[]) {
    if (!attachment.object_name) {
      onMissingObjectName?.(attachment.name ?? "Attachment");
      continue;
    }
    files.push({
      name:
        attachment.name ??
        attachment.object_name.split("/").pop() ??
        "Attachment",
      object_name: attachment.object_name,
      type: attachment.type ?? attachment.contentType ?? "file",
      size: attachment.size ?? 0,
      url: attachment.url ?? "",
      presigned_url: attachment.presigned_url,
    });
  }
  return files;
}
