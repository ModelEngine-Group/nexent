// Core Chat Types - Consolidated definitions

// Step related types
export interface StepSection {
  content: string
  expanded: boolean
}

export interface StepContent {
  id: string
  type: "model_output" | "parsing" | "execution" | "error" | "agent_new_run" | "executing" | "generating_code" | "search_content" | "card" | "search_content_placeholder" | "virtual"
  content: string
  expanded: boolean
  timestamp: number
  subType?: "thinking" | "code" | "deep_thinking"
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

// History adapter related types
export interface HistoryApiMessageItem {
  type: string
  content: string
}

export interface HistorySearchResult {
  title: string
  text: string
  url: string
  published_date: string | null
}

export interface HistoryApiMessage {
  role: "user" | "assistant"
  message: HistoryApiMessageItem[]
  message_id: number
  opinion_flag?: string
  picture?: string[]
  search?: HistorySearchResult[]
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

// API related types
export interface DialogMessage {
  content: string
  role: "user" | "assistant"
  id?: string
  doc_ids?: string[]
  images?: string[]
  is_deep_search?: boolean
  is_deep_seek?: boolean
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

export interface ApiConversationResponse {
  code: number
  data: ApiConversationDetail[]
  message: string
}

export interface DialogReference {
  chunks: any[]
}

export interface DialogRecord {
  id: string
  create_date: string
  create_time: number
  message: DialogMessage[]
  name: string
  reference: DialogReference[]
  update_date: string
  update_time: number
}

export interface ConversationListItem {
  conversation_id: number
  conversation_title: string
  create_time: number
  update_time: number
}

export interface ConversationListResponse {
  code: number
  data: ConversationListItem[]
  message: string
}

export interface UserQuestion {
  message: ChatMessageType
  index: number
}

// File preview type
export interface FilePreview {
  name: string
  type: string
  size: number
  content?: string
  url?: string
  file: File
}

// Task message type
export interface TaskMessageType extends ChatMessageType {
  type?: string;
} 