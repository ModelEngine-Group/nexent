import {
  FileImageFilled,
  FilePdfFilled,
  FileWordFilled,
  FileExcelFilled,
  FilePptFilled,
  FileTextFilled,
  FileMarkdownFilled,
  Html5Filled,
  CodeFilled,
  FileUnknownFilled,
  FileZipFilled,
} from "@ant-design/icons";

import { chatConfig } from "@/const/chatConfig";

// File limit constants from config, shared across chat and debug attachment UIs.
export const MAX_FILE_COUNT = chatConfig.maxFileCount;
export const MAX_FILE_SIZE = chatConfig.maxFileSize;

/**
 * Extract the lowercased file extension from a filename.
 *
 * Uses a bit-shift trick so a missing dot yields "" instead of the whole name.
 * @param filename - File name to parse.
 * @returns Lowercased extension without the leading dot, or "" if none.
 */
export const getFileExtension = (filename: string): string => {
  return filename
    .slice(((filename.lastIndexOf(".") - 1) >>> 0) + 2)
    .toLowerCase();
};

/**
 * Render a file-type icon for an attachment preview, colored by category.
 *
 * Shared by the chat input (32px), the debug panel compact preview (16px),
 * and the chat attachment list (32px). Callers pass the file name and content
 * type (some attachment models only have those, not a File object) plus the
 * desired pixel size.
 * @param name        - File name (used to infer the extension).
 * @param contentType - MIME type, if known; falls back to "".
 * @param iconSize    - Icon size in pixels. Defaults to 32.
 * @returns A colored Ant Design file icon element.
 */
export const getFileIcon = (
  name: string,
  contentType?: string,
  iconSize: number = 32
) => {
  const extension = getFileExtension(name);
  const fileType = contentType || "";

  if (fileType.startsWith("image/") || chatConfig.imageExtensions.includes(extension)) {
    return <FileImageFilled size={iconSize} color="#8e44ad" />;
  }
  if (chatConfig.fileIcons.pdf.includes(extension)) {
    return <FilePdfFilled size={iconSize} color="#e74c3c" />;
  }
  if (chatConfig.fileIcons.word.includes(extension)) {
    return <FileWordFilled size={iconSize} color="#3498db" />;
  }
  if (chatConfig.fileIcons.text.includes(extension)) {
    return <FileTextFilled size={iconSize} color="#7f8c8d" />;
  }
  if (chatConfig.fileIcons.markdown.includes(extension)) {
    return <FileMarkdownFilled size={iconSize} color="#34495e" />;
  }
  if (chatConfig.fileIcons.excel.includes(extension)) {
    return <FileExcelFilled size={iconSize} color="#27ae60" />;
  }
  if (chatConfig.fileIcons.powerpoint.includes(extension)) {
    return <FilePptFilled size={iconSize} color="#e67e22" />;
  }
  if (chatConfig.fileIcons.html.includes(extension)) {
    return <Html5Filled size={iconSize} color="#e67e22" />;
  }
  if (chatConfig.fileIcons.code.includes(extension)) {
    return <CodeFilled size={iconSize} color="#f39c12" />;
  }
  if (chatConfig.fileIcons.json.includes(extension)) {
    return <CodeFilled size={iconSize} color="#f1c40f" />;
  }
  if (chatConfig.fileIcons.audio.includes(extension) || fileType.startsWith("audio/")) {
    return <FileTextFilled size={iconSize} color="#16a085" />;
  }
  if (chatConfig.fileIcons.video.includes(extension) || fileType.startsWith("video/")) {
    return <FileTextFilled size={iconSize} color="#8e44ad" />;
  }
  if (chatConfig.fileIcons.compressed.includes(extension)) {
    return <FileZipFilled size={iconSize} color="#f39c12" />;
  }
  return <FileUnknownFilled size={iconSize} color="#95a5a6" />;
};
