import { chatConfig } from "@/const/chatConfig";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  FileImageFilled,
  FilePdfFilled,
  FileWordFilled,
  FileExcelFilled,
  FilePptFilled,
  FileTextFilled,
  Html5Filled,
  CodeFilled,
  FileUnknownFilled,
  FileZipFilled,
} from "@ant-design/icons";
import {
  convertImageUrlToApiUrl,
  extractObjectNameFromUrl,
} from "@/services/storageService";
import { cn } from "@/lib/utils";
import { AttachmentItem, ChatAttachmentProps } from "@/types/chat";
import { FilePreviewDrawer } from "@/components/ui/filePreviewDrawer";

/** Selected file state for preview drawer */
interface SelectedFileState {
  objectName: string;
  fileName: string;
  fileType?: string;
  fileSize?: number;
}

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

  // Image file - using lucide-react
  if (
    fileType.startsWith("image/") ||
    ["jpg", "jpeg", "png", "gif", "webp", "svg", "bmp"].includes(extension)
  ) {
    return <FileImageFilled size={iconSize} color="#8e44ad" />;
  }

  // Identify by extension name
  // Document file
  if (chatConfig.fileIcons.pdf.includes(extension)) {
    return <FilePdfFilled size={iconSize} color="#e74c3c" />;
  }
  if (chatConfig.fileIcons.word.includes(extension)) {
    return (
      <FileWordFilled size={iconSize} color="#3498db" />
    );
  }
  if (chatConfig.fileIcons.text.includes(extension)) {
    return <FileTextFilled size={iconSize} color="#7f8c8d" />;
  }
  if (chatConfig.fileIcons.markdown.includes(extension)) {
    return <FileTextFilled size={iconSize} color="#34495e" />;
  }
  // Table file
  if (chatConfig.fileIcons.excel.includes(extension)) {
    return <FileExcelFilled size={iconSize} color="#27ae60" />;
  }
  // Presentation file
  if (chatConfig.fileIcons.powerpoint.includes(extension)) {
    return <FilePptFilled size={iconSize} color="#e67e22" />;
  }

  // Code file
  if (chatConfig.fileIcons.html.includes(extension)) {
    return <Html5Filled size={iconSize} color="#e67e22" />;
  }
  if (chatConfig.fileIcons.code.includes(extension)) {
    return <CodeFilled size={iconSize} color="#f39c12" />;
  }
  if (chatConfig.fileIcons.json.includes(extension)) {
    return <CodeFilled size={iconSize} color="#f1c40f" />;
  }

  // Compressed file
  if (chatConfig.fileIcons.compressed.includes(extension)) {
    return <FileZipFilled size={iconSize} color="#f39c12" />;
  }

  // Default file icon
  return <FileUnknownFilled size={iconSize} color="#95a5a6" />;
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
  const [selectedFile, setSelectedFile] = useState<SelectedFileState | null>(null);
  const { t } = useTranslation("common");

  if (!attachments || attachments.length === 0) return null;

  /**
   * Handle file click - open preview drawer for all file types
   */
  const handleFileClick = (attachment: AttachmentItem) => {
    let objectName = attachment.object_name;
    
    if (!objectName && attachment.url) {
      objectName = extractObjectNameFromUrl(attachment.url) || undefined;
    }
    
    if (!objectName) {
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
