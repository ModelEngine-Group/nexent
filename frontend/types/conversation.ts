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
  unit_index?: number;
  unit_status?: "streaming" | "completed";
  role?: string;
  tool_name?: string;
  tool_arguments?: string | Record<string, unknown>;
}

export interface ApiMessage {
  role: "user" | "assistant";
  message: ApiMessageItem[] | string;
  message_id?: number;
  picture?: string[];
  search?: any[];
  searchByUnitId?: Record<string, any[]>;
  minio_files?: Array<
    | string
    | {
        object_name: string;
        name: string;
        type: string;
        size: number;
        url?: string;
        presigned_url?: string;
        preview_url?: string;
        download_url?: string;
      }
  >;
}

export interface StreamingMessage {
  message_id: number;
  message_index: number;
  status: "streaming";
  message_content: string;
  last_unit?: ApiMessageItem;
  units: ApiMessageItem[];
}

export interface ApiConversationDetail {
  create_time: number;
  conversation_id: number;
  agent_id?: number | null;
  message: ApiMessage[];
  streaming_message?: StreamingMessage;
}

export interface ApiConversationResponse {
  code: number;
  data: ApiConversationDetail[];
  message: string;
}
