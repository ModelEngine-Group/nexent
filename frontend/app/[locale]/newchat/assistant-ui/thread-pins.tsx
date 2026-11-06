// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  type ReactNode,
} from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { workbenchPinsQueryKey } from "@/lib/workbenchPins";
import type { WorkbenchPinItem } from "@/types/conversation";
import { conversationService } from "@/services/conversationService";
import { useForegroundRefresh } from "@/hooks/chat/useForegroundRefresh";
import { CONVERSATION_SYNC_FRESHNESS_MS } from "@/const/conversationSync";

export interface ThreadPinIdentity {
  id: string;
  remoteId?: string;
}

export const getWorkbenchPinStorageKey = (
  userId: string,
  tenantId?: string
): string =>
  `workbench.pinnedConversationIds:${JSON.stringify([tenantId ?? "", userId])}`;

export function getThreadPinKey(
  thread: ThreadPinIdentity,
  persistedConversationIds = false,
  serverConversationIds?: ReadonlyMap<string, string>
): string | undefined {
  if (!persistedConversationIds) return thread.id || undefined;
  for (const value of [
    serverConversationIds?.get(thread.id),
    thread.remoteId,
  ]) {
    if (value === undefined || !/^\d+$/.test(value)) continue;
    const numeric = Number(value);
    if (Number.isSafeInteger(numeric) && numeric > 0) return String(numeric);
  }
  return undefined;
}

/** Parse legacy serialized IDs without reading or writing browser storage. */
export function parsePinnedThreadIds(raw: string | null): ReadonlySet<string> {
  try {
    const value: unknown = JSON.parse(raw ?? "[]");
    return new Set(
      Array.isArray(value)
        ? value.filter(
            (item): item is string =>
              typeof item === "string" && item.length > 0
          )
        : []
    );
  } catch {
    return new Set();
  }
}

/** Keep ordinary ordering and optionally place the newest pins first. */
export function hoistPinnedThreads<T>(
  groups: Array<{ label: string; entries: T[] }>,
  isPinned: (entry: T) => boolean,
  getPinOrder?: (entry: T) => number
): Array<{ label: string; entries: T[] }> {
  const entries: T[] = [];
  const remaining: Array<{ label: string; entries: T[] }> = [];
  for (const group of groups) {
    const ordinary: T[] = [];
    for (const entry of group.entries) {
      if (isPinned(entry)) entries.push(entry);
      else ordinary.push(entry);
    }
    if (ordinary.length) remaining.push({ ...group, entries: ordinary });
  }
  if (getPinOrder) entries.sort((a, b) => getPinOrder(b) - getPinOrder(a));
  return entries.length
    ? [{ label: "chat.threadList.pinned", entries }, ...remaining]
    : remaining;
}

interface PinnedThreadsValue {
  pinnedIds: ReadonlySet<string>;
  serverPins?: readonly WorkbenchPinItem[];
  serverPinsRevision?: number;
  canPin: (thread: ThreadPinIdentity) => boolean;
  isPinned: (thread: ThreadPinIdentity) => boolean;
  togglePin: (thread: ThreadPinIdentity) => void;
  getPinOrder?: (thread: ThreadPinIdentity) => number;
}

const PinnedThreadsContext = createContext<PinnedThreadsValue | null>(null);

interface PinnedThreadsProviderProps {
  children: ReactNode;
  /** Null disables pinning while the authenticated identity is loading. */
  storageKey?: string | null;
  persistedConversationIds?: boolean;
  serverConversationIds?: ReadonlyMap<string, string>;
  onStorageError?: () => void;
  serverBacked?: boolean;
  conversationType?: "agent_chat" | "workbench";
}

export function PinnedThreadsProvider(props: PinnedThreadsProviderProps) {
  return (
    <ServerPinnedThreadsState key={props.storageKey ?? "disabled"} {...props} />
  );
}

function ServerPinnedThreadsState({
  children,
  storageKey,
  serverConversationIds,
  onStorageError,
  conversationType = "workbench",
}: PinnedThreadsProviderProps) {
  const client = useQueryClient();
  const queryKey = useMemo(
    () => workbenchPinsQueryKey(storageKey),
    [storageKey]
  );
  const pending = useRef(false);
  useForegroundRefresh(queryKey, Boolean(storageKey), pending);
  const query = useQuery({
    queryKey,
    staleTime: CONVERSATION_SYNC_FRESHNESS_MS,
    queryFn: () => conversationService.getWorkbenchPins(),
    enabled: Boolean(storageKey),
    refetchOnMount: true,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
  const reportedError = useRef<Error | null>(null);
  const mutation = useMutation({
    mutationFn: ({ id, pinned }: { id: number; pinned: boolean }) =>
      conversationService.setWorkbenchPin(id, pinned),
    onMutate: () => client.cancelQueries({ queryKey }),
    onSuccess: (result) => client.setQueryData(queryKey, result),
    onError: () => onStorageError?.(),
  });
  useEffect(() => {
    if (query.error && query.error !== reportedError.current)
      onStorageError?.();
    reportedError.current = query.error;
  }, [query.error, onStorageError]);
  const resolveKey = useCallback(
    (thread: ThreadPinIdentity) =>
      storageKey
        ? getThreadPinKey(thread, true, serverConversationIds)
        : undefined,
    [storageKey, serverConversationIds]
  );
  const pagePins = useMemo(
    () =>
      query.data?.items.filter(
        (item) => (item.conversation_type ?? "workbench") === conversationType
      ),
    [query.data, conversationType]
  );
  const pinnedIds = useMemo(
    () => new Set(pagePins?.map((item) => String(item.conversation_id)) ?? []),
    [pagePins]
  );
  const togglePin = useCallback(
    (thread: ThreadPinIdentity) => {
      const key = resolveKey(thread);
      if (!key || !query.data || query.isError || pending.current) return;
      pending.current = true;
      void mutation
        .mutateAsync({ id: Number(key), pinned: !pinnedIds.has(key) })
        .catch(() => {})
        .finally(() => {
          pending.current = false;
        });
    },
    [resolveKey, query.data, query.isError, mutation, pinnedIds]
  );
  const value = useMemo(() => {
    const order = new Map(
      [...pinnedIds].map((id, index) => [id, pinnedIds.size - index])
    );
    return {
      pinnedIds,
      serverPins: query.isSuccess ? pagePins : undefined,
      serverPinsRevision: query.dataUpdatedAt,
      togglePin,
      canPin: (thread: ThreadPinIdentity) =>
        Boolean(query.data) &&
        !query.isError &&
        !mutation.isPending &&
        resolveKey(thread) !== undefined,
      isPinned: (thread: ThreadPinIdentity) =>
        pinnedIds.has(resolveKey(thread) ?? ""),
      getPinOrder: (thread: ThreadPinIdentity) =>
        order.get(resolveKey(thread) ?? "") ?? -1,
    };
  }, [
    query.isSuccess,
    pagePins,
    query.data,
    query.dataUpdatedAt,
    pinnedIds,
    togglePin,
    query.isError,
    mutation.isPending,
    resolveKey,
  ]);
  return (
    <PinnedThreadsContext.Provider value={value}>
      {children}
    </PinnedThreadsContext.Provider>
  );
}

export const usePinnedThreads = () => useContext(PinnedThreadsContext);
