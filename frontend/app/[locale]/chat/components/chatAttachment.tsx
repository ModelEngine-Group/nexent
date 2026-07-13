import { chatConfig } from "@/const/chatConfig";
import { useTranslation } from "react-i18next";
import {
  convertImageUrlToApiUrl,
  extractObjectNameFromUrl,
  storageService,
} from "@/services/storageService";
import { cn } from "@/lib/utils";
import { AttachmentItem, ChatAttachmentProps } from "@/types/chat";
import { App } from "antd";
import { Download } from "lucide-react";
import { getFileExtension, getFileIcon } from "@/lib/chat/fileIconUtils";
import log from "@/lib/logger";

// Format file size
const formatFileSize = (size: number): string => {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
};

export function ChatAttachment({
  attachments,
  onImageClick,
  className = "",
}: ChatAttachmentProps) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();

  if (!attachments || attachments.length === 0) return null;

  const handleDownload = async (attachment: AttachmentItem) => {
    const objectName =
      attachment.object_name ||
      (attachment.url ? extractObjectNameFromUrl(attachment.url) : null);
    const downloadUrl = attachment.download_url;
    const fileName = attachment.name;

    try {
      if (downloadUrl) {
        const link = document.createElement("a");
        link.href = downloadUrl;
        link.download = fileName;
        link.style.display = "none";
        document.body.appendChild(link);
        link.click();
        setTimeout(() => document.body.removeChild(link), 100);
        return;
      }
      if (!objectName) {
        message.warning(t("filePreview.previewFailed"));
        return;
      }
      await storageService.downloadFile(objectName, fileName);
    } catch (err) {
      log.error("Failed to download file:", err);
      message.error(t("chatAttachment.downloadError"));
    }
  };

  const handleImageClick = (attachment: AttachmentItem) => {
    if (onImageClick && attachment.url) {
      onImageClick(attachment.url);
    }
  };

  return (
    <div className={cn("flex flex-wrap gap-2", className)}>
      {attachments.map((attachment, index) => {
        const extension = getFileExtension(attachment.name);
        const isImage =
          attachment.type === "image" ||
          (attachment.contentType &&
            attachment.contentType.startsWith("image/")) ||
          chatConfig.imageExtensions.includes(extension);

        return (
          <div
            key={`attachment-${index}`}
            className="relative group rounded-md border border-slate-200 bg-white shadow-sm hover:shadow transition-all duration-200 w-[190px] mb-1"
          >
            <div className="relative p-2 h-[52px] flex items-center">
              {isImage ? (
                <div className="flex items-center gap-3 w-full">
                  <button
                    type="button"
                    onClick={() => handleImageClick(attachment)}
                    className="w-10 h-10 flex-shrink-0 overflow-hidden rounded-md block"
                    aria-label={attachment.name}
                  >
                    {attachment.url && (
                      <img
                        src={
                          attachment.preview_url ||
                          convertImageUrlToApiUrl(attachment.url)
                        }
                        alt={attachment.name}
                        className="w-full h-full object-cover"
                        loading="lazy"
                      />
                    )}
                  </button>
                  <div className="flex-1 overflow-hidden">
                    <span
                      className="text-sm truncate block max-w-[110px] font-medium"
                      title={attachment.name}
                    >
                      {attachment.name || t("chatAttachment.image")}
                    </span>
                    <span className="text-xs text-gray-500">
                      {formatFileSize(attachment.size)}
                    </span>
                  </div>
                </div>
              ) : (
                <div className="flex items-center gap-3 w-full">
                  <div className="flex-shrink-0 transform group-hover:scale-110 transition-transform w-8 flex justify-center">
                    {getFileIcon(attachment.name, attachment.contentType)}
                  </div>
                  <div className="flex-1 overflow-hidden">
                    <span
                      className="text-sm truncate block max-w-[110px] font-medium"
                      title={attachment.name}
                    >
                      {attachment.name}
                    </span>
                    <span className="text-xs text-gray-500">
                      {formatFileSize(attachment.size)}
                    </span>
                  </div>
                </div>
              )}
            </div>
            <button
              type="button"
              aria-label={t("common.download")}
              title={t("common.download")}
              onClick={(e) => {
                e.stopPropagation();
                handleDownload(attachment);
              }}
              className="absolute top-1.5 right-1.5 p-1 rounded text-slate-500 hover:text-blue-600 hover:bg-blue-50 opacity-0 group-hover:opacity-100 focus:opacity-100 transition-opacity"
            >
              <Download size={14} />
            </button>
          </div>
        );
      })}
    </div>
  );
}
