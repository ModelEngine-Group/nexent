/**
 * Notification service for in-app notification API calls
 */

import { API_ENDPOINTS, fetchWithErrorHandling } from "./api";
import { getAuthHeaders } from "@/lib/auth";
import log from "@/lib/logger";
import type {
  NotificationListData,
  NotificationListParams,
  NotificationListResponse,
} from "@/types/notification";

const DEFAULT_UNREAD_PAGE_SIZE = 20;

export const notificationService = {
  fetchNotifications: async (
    params?: NotificationListParams
  ): Promise<NotificationListResponse | null> => {
    try {
      const response = await fetchWithErrorHandling(
        API_ENDPOINTS.notifications.list(params),
        {
          method: "GET",
          headers: getAuthHeaders(),
        }
      );

      if (!response.ok) {
        return null;
      }

      const result: NotificationListResponse = await response.json();
      return result.message === "OK" && result.data ? result : null;
    } catch (error) {
      log.warn("Failed to fetch notifications:", error);
      return null;
    }
  },

  fetchUnreadNotifications: async (
    pageSize: number = DEFAULT_UNREAD_PAGE_SIZE
  ): Promise<NotificationListData | null> => {
    const result = await notificationService.fetchNotifications({
      only_unread: true,
      page: 1,
      page_size: pageSize,
    });
    return result?.data ?? null;
  },

  fetchUnreadCount: async (): Promise<number> => {
    const data = await notificationService.fetchUnreadNotifications(1);
    return data?.pagination.total ?? 0;
  },

  markNotificationRead: async (receiverId: number): Promise<boolean> => {
    try {
      const response = await fetchWithErrorHandling(
        API_ENDPOINTS.notifications.markRead,
        {
          method: "POST",
          headers: getAuthHeaders(),
          body: JSON.stringify({ receiver_id: receiverId, mark_all: false }),
        }
      );

      return response.ok;
    } catch (error) {
      log.warn("Failed to mark notification as read:", error);
      return false;
    }
  },

  markAllNotificationsRead: async (): Promise<boolean> => {
    try {
      const response = await fetchWithErrorHandling(
        API_ENDPOINTS.notifications.markRead,
        {
          method: "POST",
          headers: getAuthHeaders(),
          body: JSON.stringify({ mark_all: true }),
        }
      );

      return response.ok;
    } catch (error) {
      log.warn("Failed to mark all notifications as read:", error);
      return false;
    }
  },
};

export default notificationService;
