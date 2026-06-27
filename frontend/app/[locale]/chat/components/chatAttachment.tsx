import { chatConfig } from "@/const/chatConfig";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  convertImageUrlToApiUrl,
  extractObjectNameFromUrl,
} from "@/services/storageService";
import { cn } from "@/lib/utils";
import { AttachmentItem, ChatAttachmentProps } from "@/types/chat";
import { FilePreviewDrawer } from "@/components/common/filePreviewDrawer";
import { App } from "antd";
import { getFileExtension, getFileIcon } from "@/lib/chat/fileIconUtils";

// Selected file state for preview drawer
interface SelectedFileState {
  objectName: string;
  fileName: string;
  fileType?: string;
  fileSize?: number;
}

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
  const [selectedFile, setSelectedFile] = useState<SelectedFileState | null>(null);
  const { t } = useTranslation("common");
  const { message } = App.useApp();

  if (!attachments || attachments.length === 0) return null;

  //Handle file click
  const handleFileClick = (attachment: AttachmentItem) => {
    let objectName = attachment.object_name;
    
    if (!objectName && attachment.url) {
      objectName = extractObjectNameFromUrl(attachment.url) || undefined;
    }
    
    if (!objectName) {
      message.warning(t("filePreview.previewFailed"));
      return;
    }

    setSelectedFile({
      objectName,
      fileName: attachment.name,
      fileType: attachment.contentType,
      fileSize: attachment.size,
    });

    // Also call external callback if provided (for compatibility with images)
    if (onImageClick && attachment.url) {
      const extension = getFileExtension(attachment.name);
      const isImage =
        attachment.type === "image" ||
        (attachment.contentType &&
          attachment.contentType.startsWith("image/")) ||
        chatConfig.imageExtensions.includes(extension);
      
      if (isImage) {
        onImageClick(attachment.url);
      }
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
            className="relative group rounded-md border border-slate-200 bg-white shadow-sm hover:shadow transition-all duration-200 w-[190px] mb-1 cursor-pointer"
            onClick={() => {
              if (attachment.url) {
                handleFileClick(attachment);
              }
            }}
          >
            <div className="relative p-2 h-[52px] flex items-center">
              {isImage ? (
                <div className="flex items-center gap-3 w-full">
                  <div className="w-10 h-10 flex-shrink-0 overflow-hidden rounded-md">
                    {attachment.url && (
                      <img
                        src={convertImageUrlToApiUrl(attachment.url)}
                        alt={attachment.name}
                        className="w-full h-full object-cover"
                        loading="lazy"
                      />
                    )}
                  </div>
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
          </div>
        );
      })}

      {/* File preview drawer */}
      {selectedFile && (
        <FilePreviewDrawer
          open={!!selectedFile}
          objectName={selectedFile.objectName}
          fileName={selectedFile.fileName}
          fileType={selectedFile.fileType}
          fileSize={selectedFile.fileSize}
          onClose={() => setSelectedFile(null)}
        />
      )}
    </div>
  );
}
