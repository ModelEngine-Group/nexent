/**
 * Types for in-app user notifications
 */

export const NOTIFICATION_EVENT_TYPES = {
  REPOSITORY_REVIEW_APPROVED: "repository_review_approved",
  REPOSITORY_REVIEW_REJECTED: "repository_review_rejected",
  REPOSITORY_REVIEW_PENDING: "repository_review_pending",
} as const;

export const NOTIFICATION_RESOURCE_TYPES = {
  AGENT_REPOSITORY: "agent_repository",
  SKILL_REPOSITORY: "skill_repository",
  MCP_REPOSITORY: "mcp_repository",
} as const;

export interface NotificationDetails {
  name?: string;
  content?: string;
  agent_repository_id?: number;
  agent_id?: number;
  [key: string]: unknown;
}

export interface NotificationItem {
  receiver_id: number;
  notification_id: number;
  event_type: string;
  resource_type: string;
  details: NotificationDetails | null;
  scope: string;
  is_read: boolean;
  create_time: string;
}

export interface NotificationPagination {
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
}

export interface NotificationListData {
  items: NotificationItem[];
  pagination: NotificationPagination;
}

export interface NotificationListResponse {
  message: string;
  data: NotificationListData;
}

export interface NotificationListParams {
  only_unread?: boolean;
  page?: number;
  page_size?: number;
}
