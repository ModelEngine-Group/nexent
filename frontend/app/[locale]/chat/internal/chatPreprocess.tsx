import { conversationService } from "@/services/conversationService";
import { storageService } from "@/services/storageService";
import { FilePreview, AgentStep } from "@/types/chat";
import log from "@/lib/logger";

// Step ID Counter
const stepIdCounter = { current: 0 };

/**
 * Parse agent steps, convert text content to structured steps
 */
export const parseAgentSteps = (
  content: string,
  defaultExpanded: boolean = false,
  t: any
): AgentStep[] => {
  const steps: AgentStep[] = [];
  const stepRegex = /<step[^>]*>([\s\S]*?)<\/step>/g;
  let match;

  while ((match = stepRegex.exec(content)) !== null) {
    const stepContent = match[1];
    const titleMatch = /<title>([\s\S]*?)<\/title>/i.exec(stepContent);
    const contentMatch = /<content>([\s\S]*?)<\/content>/i.exec(stepContent);

    const step: AgentStep = {
      id: `step-${stepIdCounter.current++}`,
      title: titleMatch ? titleMatch[1].trim() : t("chatPreprocess.step"),
      content: "",
      expanded: defaultExpanded,
      thinking: { content: "", expanded: false },
      code: { content: "", expanded: false },
      output: { content: "", expanded: false },
      metrics: "",
      contents: [],
    };

    if (contentMatch) {
      step.contents = [
        {
          id: `content-${Date.now()}-${Math.random()
            .toString(36)
            .substring(2, 7)}`,
          type: "model_output",
          content: contentMatch[1],
          expanded: false,
          timestamp: Date.now(),
        },
      ];
    }

    steps.push(step);
  }

  return steps;
};

/**
 * Handle attachment file preprocessing
 * @param content User message content
 * @param attachments Attachment list
 * @param signal AbortController signal
 * @param onProgress Preprocessing progress callback
 * @param t Translation function
 * @param conversationId Conversation ID
 * @returns Preprocessed query and processing status
 */
export const preprocessAttachments = async (
  content: string,
  attachments: FilePreview[],
  signal: AbortSignal,
  onProgress: (data: any) => void,
  t: any,
  conversationId?: number
): Promise<{
  finalQuery: string;
  success: boolean;
  error?: string;
  fileDescriptions?: Record<string, string>;
}> => {
  if (attachments.length === 0) {
    return { finalQuery: content, success: true };
  }

  try {
    // Call file preprocessing interface
    const preProcessReader = await conversationService.preprocessFiles(
      content,
      attachments.map((attachment) => attachment.file),
      conversationId,
      signal
    );

    if (!preProcessReader)
      throw new Error(t("chatPreprocess.preprocessResponseEmpty"));

    const preProcessDecoder = new TextDecoder();
    let preProcessBuffer = "";
    let finalQuery = content;
    const fileDescriptions: Record<string, string> = {};

    while (true) {
      const { done, value } = await preProcessReader.read();
      if (done) {
        break;
      }

      preProcessBuffer += preProcessDecoder.decode(value, { stream: true });

      const lines = preProcessBuffer.split("\n");
      preProcessBuffer = lines.pop() || "";

      for (const line of lines) {
        if (line.startsWith("data:")) {
          const jsonStr = line.substring(5).trim();
          try {
            const jsonData = JSON.parse(jsonStr);

            // Callback progress information
            onProgress(jsonData);

            // If it is file processing information, save file description
            if (
              jsonData.type === "file_processed" &&
              jsonData.filename &&
              jsonData.description
            ) {
              fileDescriptions[jsonData.filename] = jsonData.description;
            }

            // If it is a completion message, record the final query
            if (jsonData.type === "complete") {
              finalQuery = jsonData.final_query;
            }
          } catch (e) {
            log.error(
              t("chatPreprocess.parsingPreprocessDataFailed"),
              e,
              jsonStr
            );
          }
        }
      }
    }

    return { finalQuery, success: true, fileDescriptions };
  } catch (error) {
    log.error(t("chatPreprocess.filePreprocessingFailed"), error);
    return {
      finalQuery: content,
      success: false,
      error: error instanceof Error ? (error as Error).message : String(error),
    };
  }
};

/**
 * Create thinking step
 * @param message Message to display
 * @returns Thinking step object
 */
export const createThinkingStep = (t: any, message?: string): AgentStep => {
  const displayMessage = message || t("chatPreprocess.parsingFile");
  return {
    id: `thinking-${Date.now()}`,
    title: t("chatPreprocess.thinking"),
    content: displayMessage,
    expanded: true,
    thinking: { content: displayMessage, expanded: true },
    code: { content: "", expanded: false },
    output: { content: "", expanded: false },
    metrics: "",
    contents: [],
  };
};

/**
 * Handle file upload
 * @param file Uploaded file
 * @param setFileUrls Callback function to set file URL
 * @returns File ID
 */
export const handleFileUpload = (
  file: File,
  setFileUrls: React.Dispatch<React.SetStateAction<Record<string, string>>>,
  t: any
): string => {
  const fileId = `file-${Date.now()}-${Math.random()
    .toString(36)
    .substring(7)}`;

  // If it is not an image type, create a file preview URL
  if (!file.type.startsWith("image/")) {
    const fileUrl = URL.createObjectURL(file);
    setFileUrls((prev) => ({ ...prev, [fileId]: fileUrl }));
  }

  return fileId;
};

/**
 * Handle image upload
 * @param file Uploaded image file
 */
export const handleImageUpload = (file: File, t: any): void => {};

/**
 * Upload attachments to storage service
 * @param attachments Attachment list
 * @returns Uploaded file URLs and object names
 */
export const uploadAttachments = async (
  attachments: FilePreview[],
  t: any
): Promise<{
  uploadedFileUrls: Record<string, string>;
  objectNames: Record<string, string>;
  error?: string;
}> => {
  if (attachments.length === 0) {
    return { uploadedFileUrls: {}, objectNames: {} };
  }

  try {
    // Upload all files to storage service
    const uploadResult = await storageService.uploadFiles(
      attachments.map((attachment) => attachment.file)
    );

    // Handle upload results
    const uploadedFileUrls: Record<string, string> = {};
    const objectNames: Record<string, string> = {};

    if (uploadResult.success_count > 0) {
      uploadResult.results.forEach((result) => {
        if (result.success) {
          uploadedFileUrls[result.file_name] = result.url;
          objectNames[result.file_name] = result.object_name;
        }
      });
    }

    return { uploadedFileUrls, objectNames };
  } catch (error) {
    log.error(t("chatPreprocess.fileUploadFailed"), error);
    return {
      uploadedFileUrls: {},
      objectNames: {},
      error: error instanceof Error ? error.message : String(error),
    };
  }
};

/**
 * Create message attachment objects from attachment list
 * @param attachments Attachment list
 * @param uploadedFileUrls Uploaded file URLs
 * @param fileUrls File URL mapping
 * @returns Message attachment object array
 */
export const createMessageAttachments = (
  attachments: FilePreview[],
  uploadedFileUrls: Record<string, string>,
  fileUrls: Record<string, string>
): { type: string; name: string; size: number; url?: string }[] => {
  return attachments.map((attachment) => ({
    type: attachment.type,
    name: attachment.file.name,
    size: attachment.file.size,
    url:
      uploadedFileUrls[attachment.file.name] ||
      (attachment.type === "image"
        ? attachment.previewUrl
        : fileUrls[attachment.id]),
  }));
};

/**
 * Clean up attachment URLs
 * @param attachments Attachment list
 * @param fileUrls File URL mapping
 */
export const cleanupAttachmentUrls = (
  attachments: FilePreview[],
  fileUrls: Record<string, string>
): void => {
  // Clean up attachment preview URLs
  attachments.forEach((attachment) => {
    if (attachment.previewUrl) {
      URL.revokeObjectURL(attachment.previewUrl);
    }
  });

  // Clean up other file URLs
  Object.values(fileUrls).forEach((url) => {
    URL.revokeObjectURL(url);
  });
};
