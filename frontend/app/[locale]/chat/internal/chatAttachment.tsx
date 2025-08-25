import { useState } from "react";
import { ExternalLink } from "lucide-react";
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
  AiFillFileUnknown
} from "react-icons/ai";
import { cn } from '@/lib/utils';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { useTranslation } from 'react-i18next';

// 附件类型接口
export interface AttachmentItem {
  type: string;
  name: string;
  size: number;
  url?: string;
  contentType?: string;
}

// 附件预览组件接口
interface ChatAttachmentProps {
  attachments: AttachmentItem[];
  onImageClick?: (url: string) => void;
  className?: string;
}

// 图片查看器组件
const ImageViewer = ({ url, isOpen, onClose }: { url: string, isOpen: boolean, onClose: () => void }) => {
  if (!isOpen) return null;
  const { t } = useTranslation('common');
  
  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="max-w-4xl p-0 overflow-hidden bg-black/90">
        <DialogHeader>
          <DialogTitle className="sr-only">{t("chatAttachment.imagePreview")}</DialogTitle>
        </DialogHeader>
        <div className="flex items-center justify-center h-full">
          <img src={url} alt="Full size" className="max-h-[80vh] max-w-full" />
        </div>
      </DialogContent>
    </Dialog>
  );
};

// 文件查看器组件
const FileViewer = ({ url, name, contentType, isOpen, onClose }: { 
  url: string, 
  name: string, 
  contentType?: string, 
  isOpen: boolean, 
  onClose: () => void 
}) => {
  if (!isOpen) return null;
  const { t } = useTranslation('common');
  
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
            <p className="text-gray-600 mb-4">{t("chatAttachment.previewNotSupported")}</p>
            <a href={url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-2 px-4 py-2 bg-blue-500 text-white rounded-md hover:bg-blue-600 transition-colors">
              <ExternalLink size={16} />
              {t("chatAttachment.downloadToView")}
            </a>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
};

// 获取文件扩展名
const getFileExtension = (filename: string): string => {
  return filename.slice(((filename.lastIndexOf(".") - 1) >>> 0) + 2).toLowerCase();
};

// 获取文件图标函数 - 与输入框组件保持一致
const getFileIcon = (name: string, contentType?: string) => {
  const extension = getFileExtension(name);
  const fileType = contentType || '';
  const iconSize = 32;
  
  // 图片文件
  if (fileType.startsWith('image/') || ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'bmp'].includes(extension)) {
    return <AiFillFileImage size={iconSize} color="#8e44ad" />;
  }
  
  // 根据扩展名识别
  switch (extension) {
    // 文档文件
    case 'pdf':
      return <AiFillFilePdf size={iconSize} color="#e74c3c" />;
    case 'doc':
    case 'docx':
      return <AiFillFileWord size={iconSize} color="#3498db" />;
    case 'txt':
      return <AiFillFileText size={iconSize} color="#7f8c8d" />;
    case 'md':
      return <AiFillFileMarkdown size={iconSize} color="#34495e" />;
      
    // 表格文件
    case 'xls':
    case 'xlsx':
    case 'csv':
      return <AiFillFileExcel size={iconSize} color="#27ae60" />;
      
    // 演示文件
    case 'ppt':
    case 'pptx':
      return <AiFillFilePpt size={iconSize} color="#e67e22" />;
      
    // 代码文件
    case 'html':
    case 'htm':
      return <AiFillHtml5 size={iconSize} color="#e67e22" />;
    case 'css':
    case 'js':
    case 'ts':
    case 'jsx':
    case 'tsx':
    case 'php':
    case 'py':
    case 'java':
    case 'c':
    case 'cpp':
    case 'cs':
      return <AiFillCode size={iconSize} color="#f39c12" />;
    case 'json':
      return <AiFillCode size={iconSize} color="#f1c40f" />;
      
    // 压缩文件
    case 'zip':
    case 'rar':
    case '7z':
    case 'tar':
    case 'gz':
      return <AiFillFileZip size={iconSize} color="#f39c12" />;
      
    // 默认文件图标
    default:
      return <AiFillFileUnknown size={iconSize} color="#95a5a6" />;
  }
};

// 格式化文件大小
const formatFileSize = (size: number): string => {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
};

export function ChatAttachment({ attachments, onImageClick, className = "" }: ChatAttachmentProps) {
  const [selectedImage, setSelectedImage] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<{url: string, name: string, contentType?: string} | null>(null);
  const { t } = useTranslation('common');

  if (!attachments || attachments.length === 0) return null;

  // 处理图片点击
  const handleImageClick = (url: string) => {
    if (onImageClick) {
      // 调用外部回调
      onImageClick(url);
    } else {
      // 没有外部回调时使用内部预览
      setSelectedImage(url);
    }
  };

  // 处理文件点击
  const handleFileClick = (attachment: AttachmentItem) => {
    if (attachment.url) {
      const extension = getFileExtension(attachment.name);
      const isImage = attachment.type === 'image' || 
                    (attachment.contentType && attachment.contentType.startsWith('image/')) ||
                    ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'bmp'].includes(extension);
      
      if (isImage) {
        // 对于图片，使用图片处理逻辑
        handleImageClick(attachment.url);
      } else {
        // 对于文件，直接使用内部预览
        setSelectedFile({
          url: attachment.url,
          name: attachment.name,
          contentType: attachment.contentType
        });
      }
    }
  };

  return (
    <div className={cn("flex flex-wrap gap-2", className)}>
      {attachments.map((attachment, index) => {
        const extension = getFileExtension(attachment.name);
        const isImage = attachment.type === 'image' || 
                      (attachment.contentType && attachment.contentType.startsWith('image/')) ||
                      ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'bmp'].includes(extension);
        
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
                        src={attachment.url}
                        alt={attachment.name}
                        className="w-full h-full object-cover"
                        loading="lazy"
                      />
                    )}
                  </div>
                  <div className="flex-1 overflow-hidden">
                    <span className="text-sm truncate block max-w-[110px] font-medium" title={attachment.name}>
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
                    <span className="text-sm truncate block max-w-[110px] font-medium" title={attachment.name}>
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
      
      {/* 图片查看器 */}
      {selectedImage && (
        <ImageViewer 
          url={selectedImage} 
          isOpen={!!selectedImage} 
          onClose={() => setSelectedImage(null)} 
        />
      )}
      
      {/* 文件查看器 */}
      {selectedFile && (
        <FileViewer 
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