import { useState, useRef, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Paperclip, Mic, MicOff, Square, X, AlertCircle, Upload } from "lucide-react";
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
} from "@ant-design/icons";

import { Input } from "@/components/ui/input";
import { Button } from "antd";
import { Tooltip } from "@/components/ui/tooltip";
import { Textarea } from "@/components/ui/textarea";
import { conversationService } from "@/services/conversationService";
import { useConfig } from "@/hooks/useConfig";
import { extractColorsFromUri } from "@/lib/avatar";
import log from "@/lib/logger";
import { chatConfig } from "@/const/chatConfig";
import { FilePreview } from "@/types/chat";

import { ChatAgentSelector } from "./chatAgentSelector";

// Image viewer component
function ImageViewer({
  src,
  alt,
  onClose,
}: {
  src: string;
  alt: string;
  onClose: () => void;
}) {
  const { t } = useTranslation("common");
  return (
    <div
      className="fixed inset-0 bg-black bg-opacity-70 flex items-center justify-center z-50"
      onClick={onClose}
    >
      <div
        className="relative max-w-[90%] max-h-[90%]"
        onClick={(e) => e.stopPropagation()}
      >
        <img
          src={src}
          alt={alt}
          className="max-w-full max-h-[90vh] object-contain"
        />
        <button
          onClick={onClose}
          className="absolute -top-4 -right-4 bg-white p-1 rounded-full shadow-md hover:bg-white transition-colors"
          title={t("chatInput.close")}
        >
          <X
            size={16}
            className="text-gray-600 hover:text-red-500 transition-colors"
          />
        </button>
      </div>
    </div>
  );
}

// File preview component
function FileViewer({ file, onClose }: { file: File; onClose: () => void }) {
  const [content, setContent] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const fileType = file.type;
  const extension = getFileExtension(file.name);
  const { t } = useTranslation("common");

  // Read file content
  useEffect(() => {
    setLoading(true);
    setError(null);

    const readTextFile = () => {
      const reader = new FileReader();

      reader.onload = (event) => {
        if (event.target?.result) {
          setContent(event.target.result as string);
          setLoading(false);
        }
      };

      reader.onerror = () => {
        setError(t("chatInput.cannotReadFileContent"));
        setLoading(false);
      };

      reader.readAsText(file);
    };

    const readBinaryFile = () => {
      const objectUrl = URL.createObjectURL(file);
      setContent(objectUrl);
      setLoading(false);

      return () => {
        URL.revokeObjectURL(objectUrl);
      };
    };

    // Select the appropriate read method based on the file type
    if (isTextFile(fileType, extension)) {
      readTextFile();
    } else {
      return readBinaryFile();
    }
  }, [file, fileType, extension, t]);

  // Determine if it is a text file
  const isTextFile = (type: string, ext: string) => {
    return chatConfig.textTypes.includes(type) || chatConfig.textExtensions.includes(ext);
  };

  // Render file content
  const renderFileContent = () => {
    if (loading) {
      return (
        <div className="text-center py-8">
          {t("chatInput.loadingFileContent")}
        </div>
      );
    }

    if (error) {
      return <div className="text-center py-8 text-red-500">{error}</div>;
    }

    if (content === null) {
      return (
        <div className="text-center py-8">
          {t("chatInput.cannotPreviewFileType")}
        </div>
      );
    }

    if (fileType.startsWith("image/")) {
      return (
        <div className="flex justify-center">
          <img
            src={content}
            alt={file.name}
            className="max-w-full max-h-[70vh] object-contain"
          />
        </div>
      );
    }

    if (fileType === "application/pdf" || extension === "pdf") {
      return (
        <iframe src={content} className="w-full h-[70vh]" title={file.name} />
      );
    }

    // Display pure text files
    if (isTextFile(fileType, extension)) {
      return (
        <div className="bg-gray-50 p-4 rounded-md overflow-auto h-[70vh] whitespace-pre-wrap font-mono text-sm">
          {content}
        </div>
      );
    }

    // Files that cannot be previewed
    return (
      <div className="text-center py-16">
        <div className="flex justify-center mb-4">{getFileIcon(file)}</div>
        <p className="text-gray-600">
          {t("chatInput.thisFileTypeCannotBePreviewed")}
        </p>
      </div>
    );
  };

  return (
    <div
      className="fixed inset-0 bg-black bg-opacity-70 flex items-center justify-center z-50"
      onClick={onClose}
    >
      <div
        className="relative bg-white rounded-lg p-6 max-w-[90%] max-h-[90%] w-[800px]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-center mb-4">
          <h3 className="font-medium text-lg flex items-center gap-2">
            {getFileIcon(file)}
            <span className="truncate max-w-[600px]">{file.name}</span>
          </h3>
          <button
            onClick={onClose}
            className="bg-white p-1 rounded-full hover:bg-gray-100"
            title={t("chatInput.close")}
          >
            <X size={16} className="text-gray-600 hover:text-red-500" />
          </button>
        </div>

        <div className="border rounded-md">{renderFileContent()}</div>
      </div>
    </div>
  );
}



// Get file extension
const getFileExtension = (filename: string): string => {
  return filename
    .slice(((filename.lastIndexOf(".") - 1) >>> 0) + 2)
    .toLowerCase();
};

// Format file size
const formatFileSize = (sizeInBytes: number): string => {
  if (sizeInBytes < 1024) {
    return `${sizeInBytes} B`;
  } else if (sizeInBytes < 1024 * 1024) {
    return `${(sizeInBytes / 1024).toFixed(1)} KB`;
  } else {
    return `${(sizeInBytes / (1024 * 1024)).toFixed(1)} MB`;
  }
};

// Get file icon
const getFileIcon = (file: File) => {
  const extension = getFileExtension(file.name);
  const fileType = file.type;
  const iconSize = 32;

  // Image file
  if (fileType.startsWith("image/")) {
    return <FileImageFilled size={iconSize} color="#8e44ad" />;
  }

  // Check each file type category using config
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

  // Default file icon
  return <FileUnknownFilled size={iconSize} color="#95a5a6" />;
};

// File limit constants from config
const MAX_FILE_COUNT = chatConfig.maxFileCount;
const MAX_FILE_SIZE = chatConfig.maxFileSize;

interface ChatInputProps {
  input: string;
  isLoading: boolean;
  isStreaming?: boolean;
  isInitialMode?: boolean;
  onInputChange: (value: string) => void;
  onSend: () => void;
  onStop: () => void;
  onKeyDown: (e: React.KeyboardEvent) => void;
  onRecordingStatusChange?: (
    status: "idle" | "recording" | "connecting" | "error"
  ) => void;
  onFileUpload?: (file: File) => void;
  onImageUpload?: (file: File) => void;
  attachments?: FilePreview[];
  onAttachmentsChange?: (attachments: FilePreview[]) => void;
  selectedAgentId?: string | null;
  onAgentSelect?: (agentId: string | null) => void;
}

export function ChatInput({
  input,
  isLoading,
  isStreaming = false,
  isInitialMode = false,
  onInputChange,
  onSend,
  onStop,
  onKeyDown,
  onRecordingStatusChange,
  onFileUpload,
  onImageUpload,
  attachments = [],
  onAttachmentsChange,
  selectedAgentId = null,
  onAgentSelect,
}: ChatInputProps) {
  const [isRecording, setIsRecording] = useState(false);
  const [recordingStatus, setRecordingStatus] = useState<
    "idle" | "recording" | "connecting" | "error"
  >("idle");
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [viewingImage, setViewingImage] = useState<{
    src: string;
    alt: string;
  } | null>(null);
  const [viewingFile, setViewingFile] = useState<File | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const dropAreaRef = useRef<HTMLDivElement>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [showStopTooltip, setShowStopTooltip] = useState(false);
  const { t } = useTranslation("common");

  // Use the configuration hook to get the application avatar
  const { appConfig, getAppAvatarUrl } = useConfig();
  const avatarUrl = getAppAvatarUrl(40); // Avatar size is 40 in initial mode

  // When the recording status changes, notify the parent component
  useEffect(() => {
    onRecordingStatusChange?.(recordingStatus);
  }, [recordingStatus, onRecordingStatusChange]);

  // Add file drag and drop event listener
  useEffect(() => {
    const handleDragOver = (e: DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setIsDragging(true);
    };

    const handleDragLeave = (e: DragEvent) => {
      e.preventDefault();
      e.stopPropagation();

      // Check if it really left the drop area
      if (
        dropAreaRef.current &&
        !dropAreaRef.current.contains(e.relatedTarget as Node)
      ) {
        setIsDragging(false);
      }
    };

    const handleDragExit = (e: DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setIsDragging(false);
    };

    const handleDrop = (e: DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setIsDragging(false);

      // Process the files dropped
      if (e.dataTransfer?.files && e.dataTransfer.files.length > 0) {
        const files = Array.from(e.dataTransfer.files);
        handleFilesUpload(files);
      }
    };

    // Get the drop area
    const dropArea = dropAreaRef.current;

    if (dropArea) {
      // Add event listeners
      dropArea.addEventListener("dragover", handleDragOver as EventListener);
      dropArea.addEventListener("dragleave", handleDragLeave as EventListener);
      dropArea.addEventListener("dragexit", handleDragExit as EventListener);
      dropArea.addEventListener("drop", handleDrop as EventListener);

      // Cleanup function
      return () => {
        dropArea.removeEventListener(
          "dragover",
          handleDragOver as EventListener
        );
        dropArea.removeEventListener(
          "dragleave",
          handleDragLeave as EventListener
        );
        dropArea.removeEventListener(
          "dragexit",
          handleDragExit as EventListener
        );
        dropArea.removeEventListener("drop", handleDrop as EventListener);
      };
    }
  }, []);

  // Add clipboard paste event listener
  useEffect(() => {
    // Use the textarea element as the paste target
    const textarea = textareaRef.current;
    if (!textarea) return;

    const handlePaste = (e: ClipboardEvent) => {
      if (e.clipboardData && e.clipboardData.items) {
        // Get all items from the clipboard
        const items = e.clipboardData.items;
        let hasFiles = false;
        const pastedFiles: File[] = [];

        for (let i = 0; i < items.length; i++) {
          // Process all file types, not just images
          if (items[i].kind === "file") {
            hasFiles = true;

            // Get the file object from the clipboard
            const file = items[i].getAsFile();
            if (file) {
              // Generate a file name for the pasted file (if there is no name)
              let fileName = file.name;
              if (!fileName || fileName === "") {
                const fileExt = file.type.split("/").pop() || "";
                fileName = `pasted-file-${Date.now()}.${fileExt}`;
              }

              // Add to the pasted file list
              pastedFiles.push(new File([file], fileName, { type: file.type }));
            }
          }
        }

        // If files are found, process them
        if (hasFiles && pastedFiles.length > 0) {
          e.preventDefault();
          handleFilesUpload(pastedFiles);
        }
      }
    };

    // Only listen to the paste event of the textarea
    textarea.addEventListener("paste", handlePaste);

    // Cleanup function
    return () => {
      textarea.removeEventListener("paste", handlePaste);
    };
  }, [onImageUpload, onFileUpload]);

  // Modify keyboard event handling
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();

      // Check if there is input content, if there is no content, do not send
      if (!input.trim()) {
        return;
      }

      // Check if agent is selected
      if (!selectedAgentId) {
        setErrorMessage(t("agentSelector.pleaseSelectAgent"));
        setTimeout(() => setErrorMessage(null), 3000);
        return;
      }

      // If recording, stop recording first and then send the message
      if (isRecording && mediaRecorderRef.current) {
        mediaRecorderRef.current.stop();
        if (
          socketRef.current &&
          socketRef.current.readyState === WebSocket.OPEN
        ) {
          socketRef.current.close();
        }
        setIsRecording(false);
        setRecordingStatus("idle");
      }
      if (isStreaming) {
        setShowStopTooltip(true);
        setTimeout(() => setShowStopTooltip(false), 1500);
        return;
      }
      onKeyDown(e);
    }
  };

  // Add a function to automatically adjust the height
  const autoResizeTextarea = () => {
    const textarea = textareaRef.current;
    if (!textarea) return;

    // Reset height
    textarea.style.height = "60px";

    // Get the scroll height as the new height
    const scrollHeight = textarea.scrollHeight;

    // Set the new height, but not more than 200px
    textarea.style.height = `${Math.min(scrollHeight, 200)}px`;
  };

  // When the input changes, automatically adjust the height
  useEffect(() => {
    autoResizeTextarea();
  }, [input]);

  // Initialize height after component rendering
  useEffect(() => {
    autoResizeTextarea();
  }, []);

  // Handle recording start/stop
  const toggleRecording = async () => {
    if (isRecording) {
      // Stop recording
      if (
        mediaRecorderRef.current &&
        mediaRecorderRef.current.state === "recording"
      ) {
        mediaRecorderRef.current.stop();
      }
      if (
        socketRef.current &&
        socketRef.current.readyState === WebSocket.OPEN
      ) {
        socketRef.current.close();
      }
      setIsRecording(false);
      setRecordingStatus("idle");
    } else {
      let stream: MediaStream | null = null;
      let audioContext: AudioContext | null = null;
      let audioSource: MediaStreamAudioSourceNode | null = null;
      let processor: ScriptProcessorNode | null = null;

      try {
        setRecordingStatus("connecting");

        // 1. Request microphone permission
        const audioConstraints = conversationService.stt.getAudioConstraints();

        stream = await navigator.mediaDevices.getUserMedia(audioConstraints);

        // 2. Create audio processing chain
        audioContext = new AudioContext(
          conversationService.stt.getAudioContextOptions()
        );

        // Resume AudioContext if suspended (browser policy)
        if (audioContext.state === "suspended") {
          await audioContext.resume();
        }

        audioSource = audioContext.createMediaStreamSource(stream);
        processor = audioContext.createScriptProcessor(4096, 1, 1);

        audioSource.connect(processor);
        processor.connect(audioContext.destination);

        // 3. Create MediaRecorder
        const mediaRecorder = new MediaRecorder(stream);
        mediaRecorderRef.current = mediaRecorder;

        // 4. Create WebSocket connection
        const ws = conversationService.stt.createWebSocket();
        socketRef.current = ws;

        ws.onopen = () => {
          setIsRecording(true);
          setRecordingStatus("recording");
          try {
            mediaRecorder.start(250);
          } catch (error) {
            log.error("❌ Failed to start MediaRecorder:", error);
            setRecordingStatus("error");
            setIsRecording(false);
            cleanup();
          }
        };

        ws.onmessage = (event) => {
          try {
            const response = JSON.parse(event.data);

            if (response.result && response.result.text) {
              onInputChange(response.result.text);
            } else if (response.text) {
              onInputChange(response.text);
            } else if (response.status === "ready") {
            } else if (response.error) {
              log.error("❌ STT service error:", response.error);
              setRecordingStatus("error");
              setIsRecording(false);
              cleanup();
            }
          } catch (error) {
            log.error("⚠️ Failed to parse STT response:", error);
          }
        };

        ws.onerror = (error) => {
          log.error("❌ WebSocket error:", error);
          setRecordingStatus("error");
          setIsRecording(false);
          cleanup();
        };

        ws.onclose = (event) => {
          setIsRecording(false);
          setRecordingStatus("idle");
          cleanup();
        };

        processor.onaudioprocess = (e) => {
          try {
            if (ws.readyState === WebSocket.OPEN) {
              const inputData = e.inputBuffer.getChannelData(0);
              const pcmData =
                conversationService.stt.processAudioData(inputData);

              if (pcmData.length > 0) {
                ws.send(pcmData.buffer);
              }
            }
          } catch (error) {
            log.error("❌ Error in audio processing:", error);
            setRecordingStatus("error");
            setIsRecording(false);
            cleanup();
          }
        };

        mediaRecorder.onstop = () => {
          cleanup();
          setIsRecording(false);
          setRecordingStatus("idle");
        };

        function cleanup() {
          if (stream) {
            stream.getTracks().forEach((track) => {
              track.stop();
            });
          }

          if (audioSource) {
            try {
              audioSource.disconnect();
            } catch (e) {}
          }

          if (processor) {
            try {
              processor.disconnect();
            } catch (e) {}
          }

          if (audioContext && audioContext.state !== "closed") {
            try {
              audioContext.close();
            } catch (e) {}
          }

          if (ws && ws.readyState === WebSocket.OPEN) {
            ws.close();
          }
        }
      } catch (error) {
        log.error("❌ Failed to start recording:", error);
        setRecordingStatus("error");

        // Manual cleanup in case of initialization failure
        if (stream) {
          stream.getTracks().forEach((track) => track.stop());
        }
        if (audioContext && audioContext.state !== "closed") {
          audioContext.close();
        }
      }
    }
  };

  // Clean up resources when the component is unloaded
  useEffect(() => {
    return () => {
      if (
        mediaRecorderRef.current &&
        mediaRecorderRef.current.state === "recording"
      ) {
        mediaRecorderRef.current.stop();
      }
      if (
        socketRef.current &&
        socketRef.current.readyState === WebSocket.OPEN
      ) {
        socketRef.current.close();
      }
    };
  }, []);

  // Handle multiple file uploads
  const handleFilesUpload = (files: File[]) => {
    // Check file number limit
    if (attachments.length + files.length > MAX_FILE_COUNT) {
      setErrorMessage(
        t("chatInput.fileCountExceedsLimit", { count: MAX_FILE_COUNT })
      );
      setTimeout(() => setErrorMessage(null), 3000);
      return;
    }

    // Process multiple files
    const newAttachments: FilePreview[] = [];

    // Check the size and type of each file
    for (const file of files) {
      // Check the single file size limit
      if (file.size > MAX_FILE_SIZE) {
        setErrorMessage(
          t("chatInput.fileSizeExceedsLimit", { name: file.name })
        );
        setTimeout(() => setErrorMessage(null), 3000);
        return;
      }

      const fileId = Math.random().toString(36).substring(7);
      const extension = getFileExtension(file.name);

      // Supported image file types
      const isImage =
        file.type.startsWith("image/") ||
        chatConfig.imageExtensions.includes(extension);

      // Supported document file types
      const isDocument =
        chatConfig.documentExtensions.includes(extension) ||
        file.type === "application/pdf" ||
        file.type.includes("officedocument");

      // Supported text file types
      const isSupportedTextFile =
        chatConfig.supportedTextExtensions.includes(extension) ||
        file.type === "text/csv" ||
        file.type === "text/plain";

      if (isImage || isDocument || isSupportedTextFile) {
        // Create a preview URL for images
        const previewUrl = isImage ? URL.createObjectURL(file) : undefined;

        newAttachments.push({
          id: fileId,
          file,
          type: isImage ? chatConfig.filePreviewTypes.image : chatConfig.filePreviewTypes.file,
          fileType: file.type,
          extension,
          previewUrl,
        });

        // Call specific upload callback based on file type
        if (isImage) {
          onImageUpload?.(file);
        } else {
          onFileUpload?.(file);
        }
      } else {
        // Show error information
        setErrorMessage(
          t("chatInput.unsupportedFileType", { name: file.name })
        );
        setTimeout(() => setErrorMessage(null), 3000);
        return;
      }
    }

    // Use the onAttachmentsChange callback function to update the attachment list
    if (onAttachmentsChange && newAttachments.length > 0) {
      onAttachmentsChange([...attachments, ...newAttachments]);
    }
  };

  // Update file processing function
  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;

    // Use the common file processing function
    handleFilesUpload(Array.from(files));

    // Clear the value of the input
    e.target.value = "";
  };

  // Clean up preview URLs
  useEffect(() => {
    return () => {
      attachments.forEach((attachment) => {
        if (attachment.previewUrl) {
          URL.revokeObjectURL(attachment.previewUrl);
        }
      });
    };
  }, [attachments]);

  // Remove attachment
  const handleRemoveAttachment = (id: string) => {
    if (onAttachmentsChange) {
      // Find the attachment to delete, for cleaning up URLs
      const attachment = attachments.find((a) => a.id === id);
      if (attachment?.previewUrl) {
        URL.revokeObjectURL(attachment.previewUrl);
      }

      // Filter out the deleted attachment
      onAttachmentsChange(attachments.filter((a) => a.id !== id));
    }
  };

  // Handle viewing images
  const handleViewImage = (attachment: FilePreview) => {
    if (attachment.type === chatConfig.filePreviewTypes.image && attachment.file) {
      // To ensure the preview URL is valid, create a new blob URL
      // This avoids using a cached URL that may have expired
      const fileReader = new FileReader();
      fileReader.onload = (e) => {
        if (e.target?.result) {
          const dataUrl = e.target.result.toString();
          setViewingImage({
            src: dataUrl,
            alt: attachment.file.name || t("chatInput.image"),
          });
        }
      };
      fileReader.readAsDataURL(attachment.file);
    }
  };

  // Handle viewing files
  const handleViewFile = (file: File) => {
    setViewingFile(file);
  };

  // Render attachment preview
  const renderAttachments = () => {
    if (attachments.length === 0) return null;

    return (
      <div className="px-5 pb-2 pt-3">
        <div
          className="max-h-[156px] overflow-y-auto pr-1"
          style={{
            scrollbarWidth: "thin" as "thin",
            scrollbarColor: "#d1d5db transparent",
          }}
        >
          <div className="flex flex-wrap gap-2 items-start">
            {attachments.map((attachment) => (
              <div
                key={attachment.id}
                className="relative group rounded-md border border-slate-200 bg-white shadow-sm hover:shadow transition-all duration-200 w-[190px] mb-1"
              >
                <div className="relative p-2 h-[52px] flex items-center">
                  {attachment.type === chatConfig.filePreviewTypes.image ? (
                    <div className="flex items-center gap-3 w-full">
                      <div
                        className="w-10 h-10 flex-shrink-0 overflow-hidden rounded-md cursor-pointer"
                        onClick={() => handleViewImage(attachment)}
                      >
                        {attachment.previewUrl && (
                          <img
                            src={attachment.previewUrl}
                            alt={attachment.file.name}
                            className="w-full h-full object-cover"
                            loading="lazy"
                          />
                        )}
                      </div>
                      <div className="flex-1 overflow-hidden">
                        <span
                          className="text-sm truncate block max-w-[110px] font-medium"
                          title={attachment.file.name}
                        >
                          {attachment.file.name || t("chatInput.image")}
                        </span>
                        <span className="text-xs text-gray-500">
                          {formatFileSize(attachment.file.size)}
                        </span>
                      </div>
                    </div>
                  ) : (
                    <div className="flex items-center gap-3 w-full">
                      <div
                        className="flex-shrink-0 transform group-hover:scale-110 transition-transform w-8 flex justify-center cursor-pointer"
                        onClick={() => handleViewFile(attachment.file)}
                      >
                        {getFileIcon(attachment.file)}
                      </div>
                      <div
                        className="flex-1 overflow-hidden cursor-pointer"
                        onClick={() => handleViewFile(attachment.file)}
                      >
                        <span
                          className="text-sm truncate block max-w-[110px] font-medium"
                          title={attachment.file.name}
                        >
                          {attachment.file.name}
                        </span>
                        <span className="text-xs text-gray-500">
                          {formatFileSize(attachment.file.size)}
                        </span>
                      </div>
                    </div>
                  )}
                  <button
                    onClick={() => handleRemoveAttachment(attachment.id)}
                    className="absolute top-1 right-1 p-0.5 bg-red-500 text-white rounded-full opacity-0 group-hover:opacity-100 transition-opacity hover:bg-red-600 transform hover:scale-110 transition-transform z-10"
                    title={t("chatInput.remove")}
                  >
                    <X className="h-2.5 w-2.5" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  };

  // Render drag and drop overlay
  const renderDragOverlay = () => {
    if (!isDragging) return null;

    return (
      <div className="absolute inset-0 bg-blue-50 bg-opacity-90 border-2 border-dashed border-blue-500 rounded-3xl z-10 flex flex-col items-center justify-center">
        <div className="p-4 max-w-md text-center">
          <div className="flex justify-center mb-2">
            <div className="w-10 h-10 bg-blue-100 rounded-full flex items-center justify-center">
              <Upload className="h-5 w-5 text-blue-500" />
            </div>
          </div>
          <h3 className="text-base font-medium mb-1 text-blue-700">
            {t("chatInput.dragAndDropFilesHere")}
          </h3>
          <p className="text-xs text-blue-600">
            {t("chatInput.supportedFileFormats")}
          </p>
        </div>
      </div>
    );
  };

  // Render error message
  const renderErrorMessage = () => {
    if (!errorMessage) return null;

    return (
      <div className="absolute left-1/2 transform -translate-x-1/2 top-16 bg-red-100 border border-red-400 text-red-700 px-4 py-2 rounded-md flex items-center z-20 shadow-md">
        <AlertCircle className="h-4 w-4 mr-2" />
        <span className="text-sm">{errorMessage}</span>
      </div>
    );
  };

  const renderInputArea = () => (
    <>
      {renderDragOverlay()}
      {renderAttachments()}
      <div
        className="max-h-[300px] overflow-y-auto pt-3"
        style={{
          scrollbarWidth: "thin",
          scrollbarColor: "#d1d5db transparent",
        }}
      >
        <Textarea
          ref={textareaRef}
          value={input}
          onChange={(e) => onInputChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={t("chatInput.sendMessageTo", {
            appName: appConfig.appName,
          })}
          className="px-5 pb-3 pt-0 text-xl resize-none bg-slate-100 border-0 focus:ring-0 focus:ring-offset-0 focus-visible:ring-0 focus-visible:ring-offset-0 w-full"
          rows={1}
          style={{
            minHeight: "60px",
            overflow: "auto",
            fontSize: "18px",
          }}
        />
      </div>
      <div className="h-12 bg-slate-100 relative">
        {/* Agent selector on the left */}
        <div className="absolute left-5 top-[40%] -translate-y-1/2">
          <ChatAgentSelector
            selectedAgentId={selectedAgentId}
            onAgentSelect={onAgentSelect || (() => {})}
            disabled={isLoading || isStreaming}
            isInitialMode={isInitialMode}
          />
        </div>

        <div className="absolute right-3 top-[40%] -translate-y-1/2 flex items-center space-x-1">
          {/* Voice to text button */}
          <Tooltip
            title={
              isRecording
                ? t("chatInput.stopRecording")
                : t("chatInput.startRecording")
            }
          >
            <Button
                  type="default"
                  shape="circle"
                  size="middle"
                  className="h-10 w-10 text-slate-700 flex items-center justify-center rounded-full border border-slate-300 hover:bg-slate-200 transition-colors"
                  onClick={toggleRecording}
                  disabled={recordingStatus === "connecting" || isStreaming}
            >
              {isRecording ? (
                <MicOff className="h-5 w-5" />
              ) : (
                <Mic className="h-5 w-5" />
              )}
            </Button>
          </Tooltip>

          {/* Upload file button */}
          <Tooltip title={t("chatInput.uploadFiles")}>
            <Button
              type="default"
              shape="circle"
              size="middle"
              className="h-10 w-10 text-slate-700 flex items-center justify-center rounded-full border border-slate-300 hover:bg-slate-200 transition-colors"
              onClick={() =>
                document.getElementById("file-upload-regular")?.click()
              }
            >
              <Paperclip className="h-5 w-5" />
              <Input
                type="file"
                id="file-upload-regular"
                className="hidden"
                onChange={handleFileUpload}
                accept={`image/*,${Object.values(chatConfig.fileIcons).flat().map(ext => `.${ext}`).join(',')}`}
                multiple
              />
            </Button>
          </Tooltip>

          {isStreaming ? (
            <Tooltip
              title={t("chatInput.stopGenerating")}
              open={showStopTooltip}
              onOpenChange={setShowStopTooltip}
            >
              <Button
                onClick={onStop}
                type="primary"
                shape="circle"
                size="middle"
                className="h-10 w-10 bg-red-500 hover:bg-red-600 text-white rounded-full"
              >
                <Square className="h-5 w-5" />
              </Button>
            </Tooltip>
          ) : (
            <Button
              onClick={handleSend}
              disabled={!input.trim() || isLoading || !selectedAgentId}
              type="primary"
              shape="circle"
              size="middle"
              className={`h-10 w-10 ${
                hasUnsupportedFiles || !selectedAgentId
                  ? "bg-gray-400 cursor-not-allowed"
                  : "bg-blue-500 hover:bg-blue-600"
              } text-white rounded-full flex items-center justify-center`}
              title={
                hasUnsupportedFiles
                  ? t("chatInput.unsupportedFileTypeSimple")
                  : !selectedAgentId
                  ? t("agentSelector.pleaseSelectAgent")
                  : t("chatInput.send")
              }
            >
              <svg
                width="14"
                height="16"
                viewBox="0 0 14 16"
                fill="none"
                xmlns="http://www.w3.org/2000/svg"
              >
                <path
                  fillRule="evenodd"
                  clipRule="evenodd"
                  d="M7 16c-.595 0-1.077-.462-1.077-1.032V1.032C5.923.462 6.405 0 7 0s1.077.462 1.077 1.032v13.936C8.077 15.538 7.595 16 7 16z"
                  fill="currentColor"
                ></path>
                <path
                  fillRule="evenodd"
                  clipRule="evenodd"
                  d="M.315 7.44a1.002 1.002 0 0 1 0-1.46L6.238.302a1.11 1.11 0 0 1 1.523 0c.421.403.421 1.057 0 1.46L1.838 7.44a1.11 1.11 0 0 1-1.523 0z"
                  fill="currentColor"
                ></path>
                <path
                  fillRule="evenodd"
                  clipRule="evenodd"
                  d="M13.685 7.44a1.11 1.11 0 0 1-1.523 0L6.238 1.762a1.002 1.002 0 0 1 0-1.46 1.11 1.11 0 0 1 1.523 0l5.924 5.678c.42.403.42 1.056 0 1.46z"
                  fill="currentColor"
                ></path>
              </svg>
            </Button>
          )}
        </div>
      </div>
      <div className="mt-1 flex items-center justify-center text-xs text-muted-foreground">
        <div>
          {recordingStatus === "recording" ? (
            <span className="text-red-500">{t("chatInput.recording")}</span>
          ) : recordingStatus === "error" ? (
            <span className="text-red-500">
              {t("chatInput.recordingError")}
            </span>
          ) : (
            ""
          )}
        </div>
      </div>
    </>
  );

  // Stop recording before sending a message
  const handleSend = () => {
    // Check if agent is selected
    if (!selectedAgentId) {
      setErrorMessage(t("agentSelector.pleaseSelectAgent"));
      setTimeout(() => setErrorMessage(null), 3000);
      return;
    }

    if (isRecording && mediaRecorderRef.current) {
      mediaRecorderRef.current.stop();
      if (
        socketRef.current &&
        socketRef.current.readyState === WebSocket.OPEN
      ) {
        socketRef.current.close();
      }
      setIsRecording(false);
      setRecordingStatus("idle");
    }
    onSend();
  };

  // Check if there are any unsupported file types
  const hasUnsupportedFiles = attachments.some((attachment) => {
    const extension = getFileExtension(attachment.file.name);
    const fileType = attachment.file.type;

    const isImage =
      fileType.startsWith("image/") ||
      chatConfig.imageExtensions.includes(extension);
    const isDocument =
      chatConfig.documentExtensions.includes(extension) ||
      fileType === "application/pdf" ||
      fileType.includes("officedocument");
    const isSupportedTextFile =
      chatConfig.supportedTextExtensions.includes(extension) ||
      fileType === "text/csv" ||
      fileType === "text/plain";

    return !(isImage || isDocument || isSupportedTextFile);
  });

  // Regular mode, keep the original rendering logic
  return (
    <>
      {/* Image viewer */}
      {viewingImage && (
        <ImageViewer
          src={viewingImage.src}
          alt={viewingImage.alt}
          onClose={() => setViewingImage(null)}
        />
      )}

      {/* File viewer */}
      {viewingFile && (
        <FileViewer file={viewingFile} onClose={() => setViewingFile(null)} />
      )}

      {/* Error message */}
      {renderErrorMessage()}

      {/* Chat input part */}
      {isInitialMode ? (
        <div className="flex flex-col items-center justify-center h-full w-full max-w-5xl mx-auto mt-[-80px]">
          <div className="flex flex-col items-center mb-4">
            <div className="flex items-center mb-6">
              <div className="h-16 w-16 rounded-full overflow-hidden mr-4">
                <img
                  src={avatarUrl}
                  alt={appConfig.appName}
                  className="h-full w-full object-cover"
                />
              </div>
              <h1
                className="text-4xl font-bold bg-clip-text text-transparent"
                style={{
                  backgroundImage: (() => {
                    const colors = extractColorsFromUri(
                      appConfig.avatarUri || ""
                    );
                    const mainColor = colors.mainColor || "273746";
                    const secondaryColor = colors.secondaryColor || mainColor;
                    return `linear-gradient(180deg, #${mainColor} 0%, #${secondaryColor} 100%)`;
                  })(),
                }}
              >
                {t("chatInput.helloIm", { appName: appConfig.appName })}
              </h1>
            </div>
            <p className="text-left text-muted-foreground max-w-2xl mx-auto leading-relaxed">
              {appConfig.appDescription || t("chatInput.introMessage")}
            </p>
          </div>
          <div
            ref={dropAreaRef}
            className="relative w-full max-w-4xl rounded-3xl shadow-sm border border-slate-200 bg-slate-100 overflow-hidden"
          >
            {renderInputArea()}
          </div>
        </div>
      ) : (
        <div className="border-t-0 border-transparent bg-background">
          <div className="max-w-3xl mx-auto">
            <div
              ref={dropAreaRef}
              className="relative rounded-3xl shadow-sm border border-slate-200 bg-slate-100 overflow-hidden"
            >
              {renderInputArea()}
            </div>
          </div>
        </div>
      )}
      {/* Footer */}
      <div className="flex-shrink-0 mt-auto">
        <div
          className="text-center text-sm py-1"
          style={{
            color: "rgb(163, 163, 163)",
            position: "sticky",
            bottom: 0,
            backgroundColor: "white",
            width: "100%",
          }}
        >
          {t("chatInterface.aiGeneratedContentWarning")}
        </div>
      </div>
    </>
  );
}
