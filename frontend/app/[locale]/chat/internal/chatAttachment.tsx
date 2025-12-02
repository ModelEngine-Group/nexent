import { chatConfig } from "@/const/chatConfig";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { ExternalLink } from "lucide-react";
import { storageService, convertImageUrlToApiUrl } from "@/services/storageService";
import { message } from "antd";
import log from "@/lib/logger";
import {
  AiFillFileImage,
  AiFillFilePdf,
  AiFillFileWord,
  AiFillFileExcel,
  AiFillFilePpt,
  AiFillFileZip,
  AiFillFileText,
  AiFillFileMarkdown,
  AiFillHtml5,
  AiFillCode,
  AiFillFileUnknown,
} from "react-icons/ai";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import { AttachmentItem, ChatAttachmentProps } from "@/types/chat";

// Image viewer component
const ImageViewer = ({
  url,
  isOpen,
  onClose,
}: {
  url: string;
  isOpen: boolean;
  onClose: () => void;
}) => {
  if (!isOpen) return null;
  const { t } = useTranslation("common");
  
  // Convert image URL to backend API URL
  const imageUrl = convertImageUrlToApiUrl(url);

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="max-w-4xl p-0 overflow-hidden bg-black/90">
        <DialogHeader>
          <DialogTitle className="sr-only">
            {t("chatAttachment.imagePreview")}
          </DialogTitle>
        </DialogHeader>
        <div className="flex items-center justify-center h-full">
          <img src={imageUrl} alt="Full size" className="max-h-[80vh] max-w-full" />
        </div>
      </DialogContent>
    </Dialog>
  );
};

// File viewer component
const FileViewer = ({
  objectName,
  url,
  name,
  contentType,
  isOpen,
  onClose,
}: {
  objectName?: string;
  url?: string;
  name: string;
  contentType?: string;
  isOpen: boolean;
  onClose: () => void;
}) => {
  if (!isOpen) return null;
  const { t } = useTranslation("common");
  const [isDownloading, setIsDownloading] = useState(false);

  // Extract object_name from URL if not provided
  const extractObjectNameFromUrl = (url: string): string | null => {
    try {
      // Try to extract object_name from MinIO URL
      // MinIO URLs typically look like: http://host:port/bucket/object_name?signature
      const urlObj = new URL(url);
      const pathname = urlObj.pathname;
      // Remove leading slash and bucket name if present
      // Path format: /bucket/object_name or /object_name
      const parts = pathname.split('/').filter(Boolean);
      if (parts.length > 1) {
        // Skip bucket name, return the rest as object_name
        return parts.slice(1).join('/');
      } else if (parts.length === 1) {
        return parts[0];
      }
      return null;
    } catch (error) {
      log.error("Failed to extract object_name from URL:", error);
      return null;
    }
  };

  // Handle file download
  const handleDownload = async (e: React.MouseEvent) => {
    // Prevent dialog from closing immediately
    e.preventDefault();
    e.stopPropagation();
    
    // Check if URL is a direct http/https URL that can be accessed directly
    // Exclude backend API endpoints (containing /api/file/download/)
    if (
      url &&
      (url.startsWith("http://") || url.startsWith("https://")) &&
      !url.includes("/api/file/download/")
    ) {
      // Direct download from HTTP/HTTPS URL without backend
      const link = document.createElement("a");
      link.href = url;
      link.download = name;
      link.style.display = "none";
      document.body.appendChild(link);
      link.click();
      setTimeout(() => {
        document.body.removeChild(link);
      }, 100);
      message.success(t("chatAttachment.downloadSuccess", "File download started"));
      setTimeout(() => {
        onClose();
      }, 500);
      return;
    }
    
    // Try to get object_name from props or extract from URL
    let finalObjectName: string | undefined = objectName;
    
    if (!finalObjectName && url) {
      finalObjectName = extractObjectNameFromUrl(url) || undefined;
    }

    if (!finalObjectName) {
      // If we still don't have object_name, fall back to direct URL download
      if (url) {
        // Create a temporary link to download from URL
        const link = document.createElement("a");
        link.href = url;
        link.download = name;
        link.style.display = "none";
        document.body.appendChild(link);
        link.click();
        setTimeout(() => {
          document.body.removeChild(link);
        }, 100);
        message.success(t("chatAttachment.downloadSuccess", "File download started"));
        return;
      } else {
        message.error(t("chatAttachment.downloadError", "File object name or URL is missing"));
        return;
      }
    }

    setIsDownloading(true);
    try {
      // Start download (non-blocking, browser handles it)
      await storageService.downloadFile(finalObjectName, name);
      // Show success message immediately after triggering download
      message.success(t("chatAttachment.downloadSuccess", "File download started"));
      // Keep dialog open for a moment to show the message, then close
      setTimeout(() => {
        setIsDownloading(false);
        onClose();
      }, 500);
    } catch (error) {
      log.error("Failed to download file:", error);
      setIsDownloading(false);
      // If backend download fails and we have URL, try direct download as fallback
      if (url) {
        try {
          const link = document.createElement("a");
          link.href = url;
          link.download = name;
          link.style.display = "none";
          document.body.appendChild(link);
          link.click();
          setTimeout(() => {
            document.body.removeChild(link);
          }, 100);
          message.success(t("chatAttachment.downloadSuccess", "File download started"));
          setTimeout(() => {
            onClose();
          }, 500);
        } catch (fallbackError) {
          message.error(
            t("chatAttachment.downloadError", "Failed to download file. Please try again.")
          );
        }
      } else {
        message.error(
          t("chatAttachment.downloadError", "Failed to download file. Please try again.")
        );
      }
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="max-w-4xl p-4 overflow-hidden">
        <DialogHeader>
          <DialogTitle className="text-lg font-medium flex items-center gap-2">
            {getFileIcon(name, contentType)}
            <span className="truncate max-w-[600px]">{name}</span>
          </DialogTitle>
        </DialogHeader>

        <div className="border rounded-md max-h-[70vh] overflow-auto">
          <div className="p-16 text-center">
            <div className="flex justify-center mb-4">
              {getFileIcon(name, contentType)}
            </div>
            <p className="text-gray-600 mb-4">
              {t("chatAttachment.previewNotSupported")}
            </p>
            <button
              onClick={handleDownload}
              disabled={(!objectName && !url) || isDownloading}
              type="button"
              className="inline-flex items-center gap-2 px-4 py-2 bg-blue-500 text-white rounded-md hover:bg-blue-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <ExternalLink size={16} />
              {isDownloading
                ? t("chatAttachment.downloading", "Downloading...")
                : t("chatAttachment.downloadToView")}
            </button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
};

// Get file extension
const getFileExtension = (filename: string): string => {
  return filename
    .slice(((filename.lastIndexOf(".") - 1) >>> 0) + 2)
    .toLowerCase();
};

// Get file icon function - consistent with the input box component
const getFileIcon = (name: string, contentType?: string) => {
  const extension = getFileExtension(name);
  const fileType = contentType || "";
  const iconSize = 32;

  // Image file
  if (
    fileType.startsWith("image/") ||
    ["jpg", "jpeg", "png", "gif", "webp", "svg", "bmp"].includes(extension)
  ) {
    return <AiFillFileImage size={iconSize} color="#8e44ad" />;
  }

  // Identify by extension name
    // Document file
  if (chatConfig.fileIcons.pdf.includes(extension)) {
    return <AiFillFilePdf size={iconSize} color="#e74c3c" />;
  }
  if (chatConfig.fileIcons.word.includes(extension)) {
    return <AiFillFileWord size={iconSize} color="#3498db" />;
  }
  if (chatConfig.fileIcons.text.includes(extension)) {
    return <AiFillFileText size={iconSize} color="#7f8c8d" />;
  }
  if (chatConfig.fileIcons.markdown.includes(extension)) {
    return <AiFillFileMarkdown size={iconSize} color="#34495e" />;
  }
  // Table file
  if (chatConfig.fileIcons.excel.includes(extension)) {
    return <AiFillFileExcel size={iconSize} color="#27ae60" />;
  }
  // Presentation file
  if (chatConfig.fileIcons.powerpoint.includes(extension)) {
    return <AiFillFilePpt size={iconSize} color="#e67e22" />;
  }

  // Code file
  if (chatConfig.fileIcons.html.includes(extension)) {
    return <AiFillHtml5 size={iconSize} color="#e67e22" />;
  }
  if (chatConfig.fileIcons.code.includes(extension)) {
    return <AiFillCode size={iconSize} color="#f39c12" />;
  }
  if (chatConfig.fileIcons.json.includes(extension)) {
    return <AiFillCode size={iconSize} color="#f1c40f" />;
  }

  // Compressed file
  if (chatConfig.fileIcons.compressed.includes(extension)) {
    return <AiFillFileZip size={iconSize} color="#f39c12" />;
  }

    // Default file icon
    return <AiFillFileUnknown size={iconSize} color="#95a5a6" />;
  };

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
  const [selectedImage, setSelectedImage] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<{
    objectName?: string;
    url?: string;
    name: string;
    contentType?: string;
  } | null>(null);
  const { t } = useTranslation("common");

  if (!attachments || attachments.length === 0) return null;

  // Handle image click
  const handleImageClick = (url: string) => {
    if (onImageClick) {
      // Call external callback
      onImageClick(url);
    } else {
      // Use internal preview when there is no external callback
      setSelectedImage(url);
    }
  };

  // Handle file click
  const handleFileClick = (attachment: AttachmentItem) => {
    if (attachment.url) {
      const extension = getFileExtension(attachment.name);
      const isImage =
        attachment.type === "image" ||
        (attachment.contentType &&
          attachment.contentType.startsWith("image/")) ||
        chatConfig.imageExtensions.includes(extension);

      if (isImage) {
        // For images, use image processing logic
        handleImageClick(attachment.url);
      } else {
        // For files, use internal preview
        setSelectedFile({
          objectName: attachment.object_name,
          url: attachment.url,
          name: attachment.name,
          contentType: attachment.contentType,
        });
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

      {/* Image viewer */}
      {selectedImage && (
        <ImageViewer
          url={selectedImage}
          isOpen={!!selectedImage}
          onClose={() => setSelectedImage(null)}
        />
      )}

      {/* File viewer */}
      {selectedFile && (
        <FileViewer
          objectName={selectedFile.objectName}
          url={selectedFile.url}
          name={selectedFile.name}
          contentType={selectedFile.contentType}
          isOpen={!!selectedFile}
          onClose={() => setSelectedFile(null)}
        />
      )}
    </div>
  );
}
