import { chatConfig } from "@/const/chatConfig";
import { MESSAGE_ROLES } from "@/const/chatConfig";

export type MessageRole = typeof MESSAGE_ROLES[keyof typeof MESSAGE_ROLES];

// Step related types
export interface StepSection {
  content: string
  expanded: boolean
}

export interface StepContent {
  id: string
  type: typeof chatConfig.messageTypes.MODEL_OUTPUT |
        typeof chatConfig.messageTypes.MODEL_OUTPUT_CODE |
        typeof chatConfig.messageTypes.PARSING |
        typeof chatConfig.messageTypes.EXECUTION |
        typeof chatConfig.messageTypes.ERROR |
        typeof chatConfig.messageTypes.AGENT_NEW_RUN |
        typeof chatConfig.messageTypes.EXECUTING |
        typeof chatConfig.messageTypes.GENERATING_CODE |
        typeof chatConfig.messageTypes.SEARCH_CONTENT |
        typeof chatConfig.messageTypes.CARD |
        typeof chatConfig.messageTypes.SEARCH_CONTENT_PLACEHOLDER |
        typeof chatConfig.messageTypes.VIRTUAL |
        typeof chatConfig.messageTypes.MEMORY_SEARCH |
        typeof chatConfig.messageTypes.PREPROCESS
  content: string
  expanded: boolean
  timestamp: number
  subType?: "thinking" | "code" | "deep_thinking" | "progress" | "file_processed" | "truncation" | "complete" | "error"
  isLoading?: boolean
  _preserve?: boolean
  _messageContainer?: {
    search?: any[]
    [key: string]: any
  }
}

export interface AgentStep {
  id: string
  title: string
  content: string
  expanded: boolean
  metrics: string
  // Support for both formats
  thinking: StepSection
  code: StepSection
  output: StepSection
  // New format content array
  contents: StepContent[]
  parsingContent?: string
}

// Agent related types - imported from agentConfig

export interface ChatAgentSelectorProps {
  selectedAgentId: string | null;
  onAgentSelect: (agentId: string | null) => void;
  disabled?: boolean;
  isInitialMode?: boolean;
}

// Search result type
export interface SearchResult {
  title: string
  url: string
  text: string
  published_date: string
  source_type?: string
  filename?: string
  score?: number
  score_details?: any
  isExpanded?: boolean
  tool_sign?: string
  cite_index?: number
}

// File attachment type
export interface FileAttachment {
  name: string
  type: string
  size: number
  url?: string
  object_name?: string
  description?: string
}

// Attachment item type (for chat attachment component)
export interface AttachmentItem {
  type: string;
  name: string;
  size: number;
  url?: string;
  object_name?: string;
  contentType?: string;
}

// Chat attachment component props
export interface ChatAttachmentProps {
  attachments: AttachmentItem[];
  onImageClick?: (url: string) => void;
  className?: string;
}

// Main chat message type
export interface ChatMessageType {
  id: string
  role: "user" | "assistant" | "system"
  message_id?: number
  content: string
  opinion_flag?: string
  timestamp: Date
  sources?: {
    id: string
    title: string
    url?: string
    icon?: string
  }[]
  isComplete?: boolean
  showRawContent?: boolean
  docIds?: string[]
  images?: string[]
  isDeepSearch?: boolean
  isDeepSeek?: boolean
  sessionId?: string
  referenceId?: string
  reference?: any
  steps?: AgentStep[]
  finalAnswer?: string
  error?: string
  agentRun?: string
  searchResults?: SearchResult[]
  attachments?: FileAttachment[]
  thinking?: any[]
}

// Message processing structure
export interface ProcessedMessages {
  finalMessages: ChatMessageType[]; // User messages and final answers
  taskMessages: any[]; // Task messages, used for task windows
  // Add conversation group mapping
  conversationGroups: Map<string, any[]>; // User message ID -> related task messages
}

// Chat stream main component props
export interface ChatStreamMainProps {
  messages: ChatMessageType[];
  input: string;
  isLoading: boolean;
  isStreaming?: boolean;
  isLoadingHistoricalConversation?: boolean;
  conversationLoadError?: string;
  onInputChange: (value: string) => void;
  onSend: () => void;
  onStop: () => void;
  onKeyDown: (e: React.KeyboardEvent) => void;
  onSelectMessage?: (messageId: string) => void;
  selectedMessageId?: string;
  onImageClick?: (image: string) => void;
  attachments?: FilePreview[];
  onAttachmentsChange?: (attachments: FilePreview[]) => void;
  onFileUpload?: (file: File) => void;
  onImageUpload?: (file: File) => void;
  onOpinionChange?: (messageId: number, opinion: "Y" | "N" | null) => void;
  currentConversationId?: number;
  shouldScrollToBottom?: boolean;
  selectedAgentId?: string | null;
  onAgentSelect?: (agentId: string | null) => void;
  onCitationHover?: () => void;
  onScroll?: () => void;
}

// Card item type for task window
export interface CardItem {
  icon?: string;
  text: string;
  [key: string]: any; // Allow other properties
}

// Message handler interface for task window extensibility
export interface MessageHandler {
  canHandle: (message: any) => boolean;
  render: (
    message: any,
    t: (key: string, options?: any) => string
  ) => React.ReactNode;
}

export interface ApiMessageItem {
  type: string
  content: string
}

export interface SearchResultItem {
  cite_index: number;
  tool_sign: string;
  title: string
  text: string
  source_type: string
  url: string
  filename: string | null
  published_date: string | null
  score: number | null
  score_details: Record<string, any>
}

export interface MinioFileItem {
  type: string
  name: string
  size: number
  object_name?: string
  url?: string
  description?: string
}

export interface ApiMessage {
  role: "user" | "assistant"
  message: ApiMessageItem[]
  message_id: number
  opinion_flag?: string
  picture?: string[]
  search?: SearchResultItem[]
  search_unit_id?: { [unitId: string]: SearchResultItem[] }
  minio_files?: MinioFileItem[]
  cards?: any[]
}

export interface ApiConversationDetail {
  create_time: number
  conversation_id: number
  message: ApiMessage[]
}

export interface ConversationListItem {
  conversation_id: number
  conversation_title: string
  create_time: number
  update_time: number
}

// File preview type
export interface FilePreview {
  id: string;
  file: File;
  type: "image" | "file";
  fileType?: string;
  extension?: string;
  previewUrl?: string;
}

// Settings menu item type for admin users
export interface SettingsMenuItem {
  key: string;
  label: string;
  onClick: () => void;
}

// Chat sidebar props type
export interface ChatSidebarProps {
  conversationList: ConversationListItem[];
  selectedConversationId: number | null;
  openDropdownId: string | null;
  streamingConversations: Set<number>;
  completedConversations: Set<number>;
  onNewConversation: () => void;
  onDialogClick: (dialog: ConversationListItem) => void;
  onRename: (dialogId: number, title: string) => void;
  onDelete: (dialogId: number) => void;
  onSettingsClick: () => void;
  settingsMenuItems?: SettingsMenuItem[];
  onDropdownOpenChange: (open: boolean, id: string | null) => void;
  onToggleSidebar: () => void;
  expanded: boolean;
  userEmail: string | undefined;
  userAvatarUrl: string | undefined;
  userRole: string | undefined;
}

// Image item type for chat right panel
export interface ImageItem {
  base64Data: string;
  contentType: string;
  isLoading: boolean;
  error?: string;
  loadAttempts?: number; // Load attempts
}

// Chat right panel props type
export interface ChatRightPanelProps {
  messages: ChatMessageType[];
  onImageError: (imageUrl: string) => void;
  maxInitialImages?: number;
  isVisible?: boolean;
  toggleRightPanel?: () => void;
  selectedMessageId?: string;
}

// Task message type
export interface TaskMessageType extends ChatMessageType {
  type?: string;
}

// Message group type for task messages
export interface MessageGroup {
  message: TaskMessageType;
  cards: TaskMessageType[];
}

// Chat task message result type
export interface ChatTaskMessageResult {
  visibleMessages: TaskMessageType[];
  groupedMessages: MessageGroup[];
  hasMessages: boolean;
  hasVisibleMessages: boolean;
}

// Storage upload result type
export interface StorageUploadResult {
  message: string;
  success_count: number;
  failed_count: number;
  results: {
    success: boolean;
    object_name: string;
    file_name: string;
    file_size: number;
    content_type: string;
    upload_time: string;
    url: string;
    error?: string;
  }[];
}