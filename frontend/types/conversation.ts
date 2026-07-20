export interface ConversationListItem {
  conversation_id: number;
  conversation_title: string;
  agent_id?: number | null;
  create_time: number;
  update_time: number;
}

export interface ConversationListResponse {
  code: number;
  data: ConversationListItem[];
  message: string;
}

export interface ApiMessageItem {
  type: string;
  content: string;
}

export interface ApiMessage {
  role: "user" | "assistant";
  message: ApiMessageItem[];
  picture?: string[];
  search?: any[];
  minio_files?: Array<string | {
    object_name: string;
    name: string;
    type: string;
    size: number;
    url?: string;
  }>;
}

export interface ApiConversationDetail {
  create_time: number;
  conversation_id: number;
  agent_id?: number | null;
  message: ApiMessage[];
}

export interface ApiConversationResponse {
  code: number;
  data: ApiConversationDetail[];
  message: string;
}
