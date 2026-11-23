"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import notificationService from "@/services/notificationService";
import type { NotificationItem } from "@/types/notification";

export const NOTIFICATIONS_UNREAD_QUERY_KEY = ["notifications", "unread"] as const;

const UNREAD_PAGE_SIZE = 20;

export function useNotifications(enabled: boolean) {
  const query = useQuery({
    queryKey: NOTIFICATIONS_UNREAD_QUERY_KEY,
    queryFn: () => notificationService.fetchUnreadNotifications(UNREAD_PAGE_SIZE),
    enabled,
    staleTime: 30_000,
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
  });

  const data = query.data;

  return {
    ...query,
    unreadCount: data?.pagination.total ?? 0,
    items: (data?.items ?? []) as NotificationItem[],
  };
}

export function useMarkNotificationRead() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (receiverId: number) =>
      notificationService.markNotificationRead(receiverId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: NOTIFICATIONS_UNREAD_QUERY_KEY,
      });
    },
  });
}

export function useMarkAllNotificationsRead() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => notificationService.markAllNotificationsRead(),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: NOTIFICATIONS_UNREAD_QUERY_KEY,
      });
    },
  });
}
