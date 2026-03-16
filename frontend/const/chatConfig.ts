// Chat related configuration
export const chatConfig = {
  // Supported text file MIME types
  textTypes: [
    "text/plain",
    "text/html",
    "text/css",
    "text/javascript",
    "application/json",
    "application/xml",
    "text/markdown",
    "text/csv",
  ],

  // Supported text file extensions
  textExtensions: [
    "txt",
    "html",
    "htm",
    "css",
    "js",
    "ts",
    "jsx",
    "tsx",
    "json",
    "xml",
    "md",
    "markdown",
    "csv",
  ],

  // File limit configuration
  maxFileCount: 50,
  maxFileSize: 10 * 1024 * 1024, // Maximum 10MB per file
  
  // Supported image file extensions
  imageExtensions: ["jpg", "jpeg", "png", "gif", "webp", "svg", "bmp"],
  
  // Supported document file extensions
  documentExtensions: ["pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "epub", "html", "xml"],
  
  // Supported text document extensions
  supportedTextExtensions: ["md", "markdown", "txt", "csv", "json"],

  // File icon mapping configuration
  fileIcons: {
    // PDF files
    pdf: ["pdf"],
    
    // Word documents
    word: ["doc", "docx"],
    
    // Plain text files
    text: ["txt", "epub"],
    
    // Markdown files
    markdown: ["md"],
    
    // Excel spreadsheet files
    excel: ["xls", "xlsx", "csv"],
    
    // PowerPoint presentation files
    powerpoint: ["ppt", "pptx"],
    
    // HTML files
    html: ["html", "htm", "xml"],
    
    // Code files
    code: ["css", "js", "ts", "jsx", "tsx", "php", "py", "java", "c", "cpp", "cs"],
    
      // JSON files
    json: ["json"],

    // Compressed file
    compressed: ["zip", "rar", "7z", "tar", "gz"],
},

// File preview type constants
filePreviewTypes: {
  image: "image" as const,
  file: "file" as const,
},

// Message type constants
messageTypes: {
  // Stream response message types
  MODEL_OUTPUT: "model_output" as const,
  MODEL_OUTPUT_THINKING: "model_output_thinking" as const,
  MODEL_OUTPUT_DEEP_THINKING: "model_output_deep_thinking" as const,
  MODEL_OUTPUT_CODE: "model_output_code" as const,
  PARSING: "parsing" as const,
  EXECUTION: "execution" as const,
  EXECUTING: "executing" as const,
  AGENT_NEW_RUN: "agent_new_run" as const,
  GENERATING_CODE: "generating_code" as const,
  SEARCH_CONTENT: "search_content" as const,
  CARD: "card" as const,
  MEMORY_SEARCH: "memory_search" as const,
  PICTURE_WEB: "picture_web" as const,
  FINAL_ANSWER: "final_answer" as const,
  PARSE: "parse" as const,
  TOOL: "tool" as const,
  EXECUTION_LOGS: "execution_logs" as const,
  ERROR: "error" as const,
  STEP_COUNT: "step_count" as const,
  TOKEN_COUNT: "token_count" as const,
  SEARCH_CONTENT_PLACEHOLDER: "search_content_placeholder" as const,
  VIRTUAL: "virtual" as const,
  PREPROCESS: "preprocess" as const,
},

// Content type constants for last content type tracking
contentTypes: {
  MODEL_OUTPUT: "model_output" as const,
  MODEL_OUTPUT_CODE: "model_output_code" as const,
  PARSING: "parsing" as const,
  EXECUTION: "execution" as const,
  AGENT_NEW_RUN: "agent_new_run" as const,
  GENERATING_CODE: "generating_code" as const,
  SEARCH_CONTENT: "search_content" as const,
  CARD: "card" as const,
  MEMORY_SEARCH: "memory_search" as const,
  PREPROCESS: "preprocess" as const,
},

// TTS status constants
ttsStatus: {
  IDLE: "idle" as const,
  GENERATING: "generating" as const,
  PLAYING: "playing" as const,
  ERROR: "error" as const,
},

// Opinion constants
opinion: {
  POSITIVE: "Y" as const,
  NEGATIVE: "N" as const,
},
};

// Type definitions for better type safety
export type Opinion = typeof chatConfig.opinion[keyof typeof chatConfig.opinion] | null;
export type MessageType = typeof chatConfig.messageTypes[keyof typeof chatConfig.messageTypes];
export type ContentType = typeof chatConfig.contentTypes[keyof typeof chatConfig.contentTypes];

export const MESSAGE_ROLES = {
  USER: "user" as const,
  ASSISTANT: "assistant" as const,
  SYSTEM: "system" as const,
} as const;