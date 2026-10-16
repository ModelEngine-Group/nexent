// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { conversationService } from "@/services/conversationService";

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

export function readPinnedConversationIds(storageKey: string): string[] {
  if (typeof window === "undefined") return [];
  try {
    return [
      ...new Set(
        [...parsePinnedThreadIds(window.localStorage.getItem(storageKey))]
          .map((remoteId) => getThreadPinKey({ id: "", remoteId }, true))
          .filter((id): id is string => id !== undefined)
      ),
    ];
  } catch {
    return [];
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
  canPin: (thread: ThreadPinIdentity) => boolean;
  isPinned: (thread: ThreadPinIdentity) => boolean;
  togglePin: (thread: ThreadPinIdentity) => void;
  getPinOrder?: (thread: ThreadPinIdentity) => number;
}

const PinnedThreadsContext = createContext<PinnedThreadsValue | null>(null);
const LEGACY_STORAGE_KEY = "chat.pinnedThreadIds";

interface PinnedThreadsProviderProps {
  children: ReactNode;
  /** Null disables pinning while Workbench identity is loading. */
  storageKey?: string | null;
  persistedConversationIds?: boolean;
  serverConversationIds?: ReadonlyMap<string, string>;
  onStorageError?: () => void;
  serverBacked?: boolean;
}

export function PinnedThreadsProvider({
  storageKey = LEGACY_STORAGE_KEY,
  ...props
}: PinnedThreadsProviderProps) {
  if (props.serverBacked) {
    return (
      <ServerPinnedThreadsState
        key={storageKey ?? "disabled"}
        storageKey={storageKey}
        {...props}
      />
    );
  }
  return (
    <PinnedThreadsState
      key={storageKey ?? "disabled"}
      storageKey={storageKey}
      {...props}
    />
  );
}

function ServerPinnedThreadsState({
  children,
  storageKey,
  serverConversationIds,
  onStorageError,
}: PinnedThreadsProviderProps) {
  const client = useQueryClient();
  const queryKey = useMemo(() => ["workbench-pins", storageKey], [storageKey]);
  const query = useQuery({
    queryKey,
    queryFn: () => conversationService.getWorkbenchPins(),
    enabled: Boolean(storageKey),
    refetchOnMount: "always",
    refetchOnWindowFocus: "always",
    refetchOnReconnect: "always",
  });
  const pending = useRef(false);
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
  const pinnedIds = useMemo(
    () =>
      new Set(
        query.data?.items.map((item) => String(item.conversation_id)) ?? []
      ),
    [query.data]
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
    pinnedIds,
    togglePin,
    query.data,
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

function PinnedThreadsState({
  children,
  storageKey,
  persistedConversationIds = false,
  serverConversationIds,
  onStorageError,
}: PinnedThreadsProviderProps) {
  const [pinnedIds, setPinnedIds] = useState<ReadonlySet<string>>(() => {
    if (typeof window === "undefined" || !storageKey) return new Set();
    try {
      return parsePinnedThreadIds(window.localStorage.getItem(storageKey));
    } catch {
      return new Set();
    }
  });
  const latestPins = useRef(pinnedIds);
  const resolveKey = useCallback(
    (thread: ThreadPinIdentity) =>
      storageKey
        ? getThreadPinKey(
            thread,
            persistedConversationIds,
            serverConversationIds
          )
        : undefined,
    [storageKey, persistedConversationIds, serverConversationIds]
  );
  const togglePin = useCallback(
    (thread: ThreadPinIdentity) => {
      const key = resolveKey(thread);
      if (!key || !storageKey) return;
      const next = new Set(latestPins.current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      latestPins.current = next;
      setPinnedIds(next);
      try {
        window.localStorage.setItem(storageKey, JSON.stringify([...next]));
      } catch {
        onStorageError?.();
      }
    },
    [resolveKey, storageKey, onStorageError]
  );
  const value = useMemo(() => {
    const order = new Map([...pinnedIds].map((id, index) => [id, index]));
    return {
      pinnedIds,
      togglePin,
      getPinOrder: persistedConversationIds
        ? (thread: ThreadPinIdentity) =>
            order.get(resolveKey(thread) ?? "") ?? -1
        : undefined,
      canPin: (thread: ThreadPinIdentity) => resolveKey(thread) !== undefined,
      isPinned: (thread: ThreadPinIdentity) => {
        const key = resolveKey(thread);
        return key !== undefined && pinnedIds.has(key);
      },
    };
  }, [pinnedIds, togglePin, resolveKey, persistedConversationIds]);
  return (
    <PinnedThreadsContext.Provider value={value}>
      {children}
    </PinnedThreadsContext.Provider>
  );
}

export const usePinnedThreads = () => useContext(PinnedThreadsContext);
