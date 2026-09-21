"use client";

import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import type {
  UseQueryResult,
} from "@tanstack/react-query";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { conversationService } from "@/services/conversationService";
import { ConversationListItem, ConversationListPage, ConversationListMetadata } from "@/types/conversation";
import log from "@/lib/logger";
import { getConversationDateBoundaries } from "@/lib/conversationViewport";

const CONVERSATION_MANAGE_QUERY_KEY = ["conversations", "manage"] as const;

export interface ConversationManageFilters {
  startDateMs?: number;
  endDateMs?: number;
  agentId?: number | null;
  keyword?: string;
}

export interface ConversationManage {
  conversationList: ConversationListItem[];
  isLoading: boolean;
  isError: boolean;
  error: Error | null;
  total: number;
  refetch: () => Promise<void>;
  filters: ConversationManageFilters;
  setFilters: React.Dispatch<React.SetStateAction<ConversationManageFilters>>;
  resetFilters: () => void;
}

export const useConversationManage = (): ConversationManage => {
  const { t } = useTranslation("common");
  const queryClient = useQueryClient();
  const [dateBoundaries] = useState(getConversationDateBoundaries);
  const [filters, setFilters] = useState<ConversationManageFilters>({});

  const queryKey = useMemo(
    () => [...CONVERSATION_MANAGE_QUERY_KEY, filters] as const,
    [filters]
  );

  const query = useQuery<ConversationListPage, Error>({
    queryKey,
    queryFn: async (): Promise<ConversationListPage> => {
      return conversationService.getList({
        offset: 0,
        limit: 20,
        todayStartMs: dateBoundaries.todayStartMs,
        weekStartMs: dateBoundaries.weekStartMs,
        ...filters,
      });
    },
    staleTime: 30_000,
    gcTime: 0,
  });

  const conversationList = query.data?.items ?? [];
  const total = query.data?.metadata.total ?? 0;

  const refetch = useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey });
  }, [queryClient, queryKey]);

  const resetFilters = useCallback(() => {
    setFilters({});
  }, []);

  return {
    conversationList,
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    total,
    refetch,
    filters,
    setFilters,
    resetFilters,
  };
};