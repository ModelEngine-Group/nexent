"use client";

import { type FC, useState, useEffect } from "react";
import {
  ArchiveIcon,
  CodeIcon,
  DownloadIcon,
  FileIcon,
  FileSpreadsheetIcon,
  FileTextIcon,
  MusicIcon,
  PlusIcon,
  PresentationIcon,
  VideoIcon,
  XIcon,
} from "lucide-react";
import {
  ComposerPrimitive,
  MessagePrimitive,
  AttachmentPrimitive,
  type CompleteAttachment,
} from "@assistant-ui/react";
import { TooltipIconButton } from "./tooltip-icon-button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
} from "@/components/ui/dialog";
import { FilePreviewDrawer } from "@/components/common/filePreviewDrawer";
import { storageService } from "@/services/storageService";
import log from "@/lib/logger";
import { type AttachmentType } from "../utils/attachment-type";

const useFileSrc = (file: File | undefined) => {
  const [src, setSrc] = useState<string | undefined>(undefined);

  useEffect(() => {
    if (!file) {
      setSrc(undefined);
      return;
    }

    const objectUrl = URL.createObjectURL(file);
    setSrc(objectUrl);

    return () => {
      URL.revokeObjectURL(objectUrl);
    };
  }, [file]);

  return src;
};

const getFileIcon = (filename: string | undefined, contentType?: string) => {
  const ext = filename?.split(".").pop()?.toLowerCase() || "";
  const mimeType = contentType?.toLowerCase() || "";

  if (["jpg", "jpeg", "png", "gif", "webp", "svg", "bmp", "ico"].includes(ext)) {
    return null; // Will show thumbnail instead
  }
  if (["doc", "docx", "odt", "rtf", "txt"].includes(ext) || mimeType.includes("word")) {
    return <FileTextIcon className="size-5" />;
  }
  if (["xls", "xlsx", "csv", "ods"].includes(ext) || mimeType.includes("spreadsheet") || mimeType.includes("excel")) {
    return <FileSpreadsheetIcon className="size-5" />;
  }
  if (["ppt", "pptx", "odp"].includes(ext) || mimeType.includes("presentation")) {
    return <PresentationIcon className="size-5" />;
  }
  if (["pdf"].includes(ext) || mimeType.includes("pdf")) {
    return <FileTextIcon className="size-5" />;
  }
  if (["zip", "rar", "7z", "tar", "gz"].includes(ext) || mimeType.includes("zip") || mimeType.includes("archive")) {
    return <ArchiveIcon className="size-5" />;
  }
  if (["mp4", "avi", "mov", "wmv", "mkv", "webm"].includes(ext) || mimeType.includes("video")) {
    return <VideoIcon className="size-5" />;
  }
  if (["mp3", "wav", "ogg", "flac", "aac", "m4a"].includes(ext) || mimeType.includes("audio")) {
    return <MusicIcon className="size-5" />;
  }
  if (["js", "ts", "jsx", "tsx", "py", "java", "cpp", "c", "h", "css", "html", "json", "xml", "yaml", "yml"].includes(ext)) {
    return <CodeIcon className="size-5" />;
  }

  return <FileIcon className="size-5" />;
};

const formatFileSize = (size: number | undefined) => {
  if (size === undefined) return "";
  if (size < 1024) return `${size} B`;

  const units = ["KB", "MB", "GB", "TB"];
  let value = size / 1024;
  let unitIndex = 0;

  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }

  const precision = value >= 10 ? 0 : 1;
  return `${value.toFixed(precision)} ${units[unitIndex]}`;
};

interface AttachmentViewModel {
  name?: string;
  type?: string;
  contentType?: string;
  file?: File;
  size?: number;
  content?: Array<{ type: string; image?: string; data?: string }>;
  object_name?: string;
  url?: string;
  presigned_url?: string;
  preview_url?: string;
  download_url?: string;
}

const triggerUrlDownload = (url: string, filename: string) => {
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.style.display = "none";
  document.body.appendChild(link);
  link.click();
  window.setTimeout(() => link.remove(), 100);
};

const AttachmentPreview: FC<{
  attachment: AttachmentViewModel;
  mode: "composer" | "message";
}> = ({ attachment, mode }) => {
  const [isLocalPreviewOpen, setIsLocalPreviewOpen] = useState(false);
  const [isRemotePreviewOpen, setIsRemotePreviewOpen] = useState(false);

  const type: AttachmentType =
    attachment.type === "image" ||
    attachment.type === "document" ||
    attachment.type === "file"
      ? attachment.type
      : "file";
  const name = attachment.name || "Untitled";
  const contentType = attachment.contentType;
  const extension = name.split(".").pop()?.toLowerCase() || "";
  const isImage =
    type === "image" ||
    contentType?.startsWith("image/") === true ||
    ["jpg", "jpeg", "png", "gif", "webp", "svg", "bmp", "ico"].includes(
      extension,
    );
  const isComposer = mode === "composer";
  const localImageUrl = useFileSrc(
    isComposer && isImage ? attachment.file : undefined,
  );
  const remoteFileUrl =
    attachment.preview_url ||
    attachment.presigned_url ||
    attachment.url ||
    attachment.content?.[0]?.image ||
    attachment.content?.[0]?.data;
  const thumbnailUrl = isComposer ? localImageUrl : remoteFileUrl;
  const objectName = attachment.object_name || "";
  const canOpenRemotePreview = Boolean(objectName || attachment.preview_url);

  const handleCardClick = () => {
    if (isComposer) {
      if (isImage && localImageUrl) setIsLocalPreviewOpen(true);
      return;
    }
    if (canOpenRemotePreview) setIsRemotePreviewOpen(true);
  };

  const handleDownload = async () => {
    try {
      if (attachment.download_url) {
        triggerUrlDownload(attachment.download_url, name);
      } else if (objectName) {
        await storageService.downloadFile(objectName, name);
      } else if (remoteFileUrl) {
        triggerUrlDownload(remoteFileUrl, name);
      }
    } catch (error) {
      log.error("Failed to download attachment:", error);
    }
  };

  return (
    <>
      <div className="group/attachment relative inline-flex">
        <div
          className={`flex max-w-65 items-center gap-3 rounded-xl border py-2 pl-2 text-left transition-colors hover:border-blue-200 hover:bg-blue-50 ${
            isComposer ? "pr-3" : "pr-2"
          } ${isComposer && !isImage ? "cursor-default" : "cursor-pointer"}`}
          onClick={handleCardClick}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              handleCardClick();
            }
          }}
          role={isComposer && !isImage ? undefined : "button"}
          tabIndex={isComposer && !isImage ? undefined : 0}
          aria-label={isComposer && !isImage ? undefined : `Preview ${name}`}
        >
          <div className="flex size-10 shrink-0 items-center justify-center overflow-hidden rounded-xl bg-blue-100 text-blue-600 dark:bg-blue-900 dark:text-blue-300">
            {isImage && thumbnailUrl ? (
              <img
                src={thumbnailUrl}
                alt={name}
                className="size-full object-cover"
              />
            ) : (
              getFileIcon(name, contentType)
            )}
          </div>
          <div className="min-w-0 flex-1">
            <p className="max-w-[120px] truncate text-sm leading-5 text-blue-900 dark:text-blue-100">
              {name}
            </p>
            <p className="max-w-[120px] truncate text-xs text-blue-600 dark:text-blue-400">
              {formatFileSize(attachment.file?.size ?? attachment.size)}
            </p>
          </div>
          {!isComposer && (
            <TooltipIconButton
              tooltip="Download"
              type="button"
              className="size-7 shrink-0 text-blue-700 hover:bg-blue-100 dark:text-blue-200 dark:hover:bg-blue-800"
              onClick={(event) => {
                event.preventDefault();
                event.stopPropagation();
                void handleDownload();
              }}
            >
              <DownloadIcon className="size-4" />
            </TooltipIconButton>
          )}
        </div>

        {isComposer && (
          <AttachmentPrimitive.Remove
            aria-label={`Remove ${name}`}
            className="absolute -right-1 -top-1 flex size-5 items-center justify-center rounded-full bg-blue-100 text-blue-700 opacity-0 transition-opacity hover:bg-blue-200 group-hover/attachment:opacity-100 focus:opacity-100 dark:bg-blue-900 dark:text-blue-200 dark:hover:bg-blue-800"
            onPointerDown={(event) => event.stopPropagation()}
            onClick={(event) => event.stopPropagation()}
          >
            <XIcon className="size-3.5" />
          </AttachmentPrimitive.Remove>
        )}
      </div>

      <Dialog open={isLocalPreviewOpen} onOpenChange={setIsLocalPreviewOpen}>
        <DialogContent
          className="flex max-h-[80vh] max-w-3xl flex-col p-0"
          onOpenAutoFocus={(event) => event.preventDefault()}
        >
          <DialogHeader className="border-b px-4 py-3">
            <h2 className="truncate text-base font-medium">{name}</h2>
          </DialogHeader>
          {localImageUrl && (
            <div className="flex min-h-0 flex-1 items-center justify-center p-4">
              <img
                src={localImageUrl}
                alt={name}
                className="max-h-[calc(70vh-60px)] max-w-full object-contain"
              />
            </div>
          )}
        </DialogContent>
      </Dialog>

      {!isComposer && isRemotePreviewOpen && (
        <FilePreviewDrawer
          open={isRemotePreviewOpen}
          objectName={objectName}
          fileName={name}
          fileType={contentType || attachment.type}
          fileSize={attachment.size}
          previewUrl={attachment.preview_url}
          downloadUrl={attachment.download_url}
          onClose={() => setIsRemotePreviewOpen(false)}
        />
      )}
    </>
  );
};

export const ComposerAddAttachment: FC = () => {
  return (
    <ComposerPrimitive.AddAttachment asChild multiple>
      <TooltipIconButton tooltip="Add attachment">
        <PlusIcon className="size-4" />
      </TooltipIconButton>
    </ComposerPrimitive.AddAttachment>
  );
};

export const ComposerAttachments: FC = () => {
  return (
    <div className="flex flex-wrap gap-2 px-2 py-1">
      <ComposerPrimitive.Attachments>
        {({ attachment }) => {
          return (
            <AttachmentPreview
              attachment={attachment}
              mode="composer"
            />
          );
        }}
      </ComposerPrimitive.Attachments>
    </div>
  );
};

export const MessageAttachments: FC<{ align?: "start" | "end" }> = ({
  align = "end",
}) => {
  return (
    <div className="mt-2">
      <div
        className={`flex flex-wrap gap-2 ${align === "start" ? "justify-start" : "justify-end"}`}
      >
        <MessagePrimitive.Attachments>
          {({ attachment }) => {
            return (
              <AttachmentPreview
                attachment={attachment}
                mode="message"
              />
            );
          }}
        </MessagePrimitive.Attachments>
      </div>
    </div>
  );
};

export const UserMessageAttachments: FC = () => (
  <MessageAttachments align="end" />
);

export const AssistantMessageAttachments: FC<{
  attachments?: CompleteAttachment[];
}> = ({ attachments }) => {
  return (
    <div className="mt-2">
      <div className="flex flex-wrap gap-2 justify-start">
        {(attachments ?? []).map((attachment) => (
          <AttachmentPreview
            key={attachment.id}
            attachment={attachment}
            mode="message"
          />
        ))}
      </div>
    </div>
  );
};
