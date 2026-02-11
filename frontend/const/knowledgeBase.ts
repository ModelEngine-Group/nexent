// Knowledge base related constants

// Document status constants
export const DOCUMENT_STATUS = {
  WAIT_FOR_PROCESSING: "WAIT_FOR_PROCESSING",
  WAIT_FOR_FORWARDING: "WAIT_FOR_FORWARDING",
  PROCESSING: "PROCESSING",
  FORWARDING: "FORWARDING",
  COMPLETED: "COMPLETED",
  PROCESS_FAILED: "PROCESS_FAILED",
  FORWARD_FAILED: "FORWARD_FAILED",
} as const;

// Non-terminal statuses (still processing)
export const NON_TERMINAL_STATUSES: string[] = [
  DOCUMENT_STATUS.WAIT_FOR_PROCESSING,
  DOCUMENT_STATUS.PROCESSING,
  DOCUMENT_STATUS.WAIT_FOR_FORWARDING,
  DOCUMENT_STATUS.FORWARDING,
];

// Document action type constants
export const DOCUMENT_ACTION_TYPES = {
  FETCH_SUCCESS: "FETCH_SUCCESS",
  SELECT_DOCUMENT: "SELECT_DOCUMENT",
  SELECT_DOCUMENTS: "SELECT_DOCUMENTS",
  SELECT_ALL: "SELECT_ALL",
  SET_UPLOAD_FILES: "SET_UPLOAD_FILES",
  SET_UPLOADING: "SET_UPLOADING",
  SET_LOADING_DOCUMENTS: "SET_LOADING_DOCUMENTS",
  DELETE_DOCUMENT: "DELETE_DOCUMENT",
  SET_LOADING_KB_ID: "SET_LOADING_KB_ID",
  CLEAR_DOCUMENTS: "CLEAR_DOCUMENTS",
  ERROR: "ERROR",
} as const;

// Knowledge base action type constants
export const KNOWLEDGE_BASE_ACTION_TYPES = {
  FETCH_SUCCESS: "FETCH_SUCCESS",
  SELECT_KNOWLEDGE_BASE: "SELECT_KNOWLEDGE_BASE",
  SET_ACTIVE: "SET_ACTIVE",
  SET_MODEL: "SET_MODEL",
  DELETE_KNOWLEDGE_BASE: "DELETE_KNOWLEDGE_BASE",
  ADD_KNOWLEDGE_BASE: "ADD_KNOWLEDGE_BASE",
  LOADING: "LOADING",
  SET_SYNC_LOADING: "SET_SYNC_LOADING",
  SET_DATA_MATE_SYNC_ERROR: "SET_DATA_MATE_SYNC_ERROR",
  ERROR: "ERROR",
} as const;

// UI layout configuration, internally manages height ratios of each section
export const UI_CONFIG = {
  TITLE_BAR_HEIGHT: "56.8px", // Fixed height for title bar
  UPLOAD_COMPONENT_HEIGHT: "250px", // Fixed height for upload component
};

// Column width constants configuration for unified management
export const COLUMN_WIDTHS = {
  NAME: "47%", // Document name column width
  STATUS: "11%", // Status column width
  SIZE: "11%", // Size column width
  DATE: "20%", // Date column width
  ACTION: "11%", // Action column width
};

// Document name display configuration
export const DOCUMENT_NAME_CONFIG = {
  MAX_WIDTH: "450px", // Maximum width for document name
  TEXT_OVERFLOW: "ellipsis", // Show ellipsis for overflow text
  WHITE_SPACE: "nowrap", // No line break
  OVERFLOW: "hidden", // Hide overflow
};

// Layout and spacing configuration
export const LAYOUT = {
  // Cells and spacing
  CELL_PADDING: "px-3 py-1.5", // Cell padding
  TEXT_SIZE: "text-sm", // Standard text size
  HEADER_TEXT: "text-sm font-semibold text-gray-600 uppercase tracking-wider", // Header text style

  // Knowledge base title area
  KB_HEADER_PADDING: "p-3", // Knowledge base title area padding
  KB_TITLE_SIZE: "text-lg", // Knowledge base title text size
  KB_TITLE_MARGIN: "ml-3", // Knowledge base title left margin

  // Table row styles
  TABLE_ROW_HOVER: "hover:bg-gray-50", // Table row hover background
  TABLE_HEADER_BG: "bg-gray-50", // Table header background color
  TABLE_ROW_DIVIDER: "divide-y divide-gray-200", // Table row divider

  // Icons and buttons
  ICON_SIZE: "text-lg", // File icon size
  ICON_MARGIN: "mr-2", // File icon right margin
  ACTION_TEXT: "text-red-500 hover:text-red-700 font-medium text-xs", // Action button text style
};

// UI action type constants
export const UI_ACTION_TYPES = {
  SET_DRAGGING: "SET_DRAGGING",
  TOGGLE_CREATE_MODAL: "TOGGLE_CREATE_MODAL",
  TOGGLE_DOC_MODAL: "TOGGLE_DOC_MODAL",
  ADD_NOTIFICATION: "ADD_NOTIFICATION",
  REMOVE_NOTIFICATION: "REMOVE_NOTIFICATION",
} as const;

// Notification type constants
export const NOTIFICATION_TYPES = {
  SUCCESS: "success",
  ERROR: "error",
  INFO: "info",
  WARNING: "warning",
} as const;

// File extension constants
export const FILE_EXTENSIONS = {
  PDF: "pdf",
  DOC: "doc",
  DOCX: "docx",
  XLS: "xls",
  XLSX: "xlsx",
  PPT: "ppt",
  PPTX: "pptx",
  TXT: "txt",
  MD: "md",
} as const;

// File type constants
export const FILE_TYPES = {
  PDF: "PDF",
  WORD: "Word",
  EXCEL: "Excel",
  POWERPOINT: "PowerPoint",
  TEXT: "Text",
  MARKDOWN: "Markdown",
  UNKNOWN: "Unknown",
} as const;

// File extension to type mapping
export const EXTENSION_TO_TYPE_MAP = {
  [FILE_EXTENSIONS.PDF]: FILE_TYPES.PDF,
  [FILE_EXTENSIONS.DOC]: FILE_TYPES.WORD,
  [FILE_EXTENSIONS.DOCX]: FILE_TYPES.WORD,
  [FILE_EXTENSIONS.XLS]: FILE_TYPES.EXCEL,
  [FILE_EXTENSIONS.XLSX]: FILE_TYPES.EXCEL,
  [FILE_EXTENSIONS.PPT]: FILE_TYPES.POWERPOINT,
  [FILE_EXTENSIONS.PPTX]: FILE_TYPES.POWERPOINT,
  [FILE_EXTENSIONS.TXT]: FILE_TYPES.TEXT,
  [FILE_EXTENSIONS.MD]: FILE_TYPES.MARKDOWN,
} as const;
