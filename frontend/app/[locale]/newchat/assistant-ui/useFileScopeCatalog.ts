// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import aidpKnowledgeService from "@/ext_components/aidp/shared/services/aidpKnowledgeService";

export const FILE_SCOPE_BROWSE_PAGE_SIZE = 10;
const SEARCH_PAGE_SIZE = 20;
const SEARCH_MIN_LENGTH = 2;
const SEARCH_CONCURRENCY = 3;
const SEARCH_DEBOUNCE_MS = 350;

export interface FileScopeFile {
  kdsId: string;
  fileUuid: string;
  fileName: string;
  fileType?: string;
  kdsName: string;
}

export interface FileScopeKnowledgeBase {
  id: string;
  name: string;
}

interface UseFileScopeCatalogOptions {
  knowledgeBases: readonly FileScopeKnowledgeBase[];
  enabled: boolean;
  searchTerm: string;
}

interface PageCache {
  files: FileScopeFile[];
  total: number;
  hasMore: boolean;
}

export interface FileScopeGroupState {
  files: FileScopeFile[];
  page: number;
  total: number;
  hasMore: boolean;
  loaded: boolean;
  loading: boolean;
  error: boolean;
}

export interface FileScopeSearchGroup {
  files: FileScopeFile[];
  hasMore: boolean;
}

export interface FileScopeCatalogState {
  groups: FileScopeKnowledgeBase[];
  groupStates: Record<string, FileScopeGroupState>;
  browsePageSize: number;
  loadGroup: (id: string, page?: number) => void;
  reload: () => void;
  searchActive: boolean;
  searchResults: Record<string, FileScopeSearchGroup>;
  searchSettled: boolean;
  searchHasSuccess: boolean;
}

const emptyGroupState = (): FileScopeGroupState => ({
  files: [],
  page: 1,
  total: 0,
  hasMore: false,
  loaded: false,
  loading: false,
  error: false,
});

const COMPLETED_STATUS_ALIASES: Record<string, number> = {
  COMPLETED: 1,
  SUCCESS: 1,
};

function documentStatusCode(value: unknown): number | null {
  if (typeof value === "number") return value;
  if (typeof value === "string" && /^\d+$/.test(value.trim())) {
    return Number(value.trim());
  }
  if (typeof value === "string") {
    return COMPLETED_STATUS_ALIASES[value.trim().toUpperCase()] ?? null;
  }
  return null;
}

function isSearchableDocument(item: {
  status?: unknown;
  file_status?: unknown;
  file_uuid?: unknown;
}): boolean {
  if (!item.file_uuid) return false;
  const deleting = documentStatusCode(item.file_status);
  if (deleting === 1 || deleting === 2) return false;
  const status = documentStatusCode(item.status);
  return status === null || status === 1;
}

function mapFiles(
  items: Array<{
    file_uuid?: unknown;
    file_name?: unknown;
    file_type?: unknown;
    status?: unknown;
    file_status?: unknown;
  }>,
  knowledgeBase: FileScopeKnowledgeBase
): FileScopeFile[] {
  const seen = new Set<string>();
  const files: FileScopeFile[] = [];
  items.filter(isSearchableDocument).forEach((item) => {
    const fileUuid = String(item.file_uuid);
    if (seen.has(fileUuid)) return;
    seen.add(fileUuid);
    files.push({
      kdsId: knowledgeBase.id,
      fileUuid,
      fileName: String(item.file_name || item.file_uuid),
      fileType: item.file_type ? String(item.file_type) : undefined,
      kdsName: knowledgeBase.name,
    });
  });
  return files;
}

export function useFileScopeCatalog({
  knowledgeBases,
  enabled,
  searchTerm,
}: UseFileScopeCatalogOptions): FileScopeCatalogState {
  const [groupStates, setGroupStates] = useState<
    Record<string, FileScopeGroupState>
  >({});
  const [searchResults, setSearchResults] = useState<
    Record<string, FileScopeSearchGroup>
  >({});
  const [searchSettled, setSearchSettled] = useState(false);
  const [searchHasSuccess, setSearchHasSuccess] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);

  const serializedKnowledgeBases = JSON.stringify(knowledgeBases);
  const groups = useMemo<FileScopeKnowledgeBase[]>(
    () => JSON.parse(serializedKnowledgeBases) as FileScopeKnowledgeBase[],
    [serializedKnowledgeBases]
  );
  const groupsRef = useRef(groups);
  useEffect(() => {
    groupsRef.current = groups;
  }, [groups]);
  const groupsKey = useMemo(
    () =>
      groups
        .map((group) => `${group.id}:${group.name}`)
        .sort()
        .join("|"),
    [groups]
  );

  const pagesRef = useRef<Record<string, Record<number, PageCache>>>({});
  const loadingKeysRef = useRef<Set<string>>(new Set());
  const browseControllersRef = useRef<Map<string, AbortController>>(new Map());
  const searchControllerRef = useRef<AbortController | null>(null);
  const searchGenerationRef = useRef(0);
  const initializedKeyRef = useRef("");
  const initializedReloadRef = useRef(-1);

  const abortBrowse = useCallback(() => {
    browseControllersRef.current.forEach((controller) => controller.abort());
    browseControllersRef.current.clear();
    loadingKeysRef.current.clear();
  }, []);

  const abortSearch = useCallback(() => {
    searchGenerationRef.current += 1;
    searchControllerRef.current?.abort();
    searchControllerRef.current = null;
  }, []);

  const loadGroup = useCallback((id: string, page = 1) => {
    const knowledgeBase = groupsRef.current.find((group) => group.id === id);
    if (!knowledgeBase) return;

    const cached = pagesRef.current[id]?.[page];
    if (cached) {
      browseControllersRef.current.get(id)?.abort();
      browseControllersRef.current.delete(id);
      setGroupStates((current) => ({
        ...current,
        [id]: {
          ...(current[id] ?? emptyGroupState()),
          ...cached,
          page,
          loaded: true,
          loading: false,
          error: false,
        },
      }));
      return;
    }

    const requestKey = `${id}:${page}`;
    if (loadingKeysRef.current.has(requestKey)) return;
    loadingKeysRef.current.add(requestKey);
    browseControllersRef.current.get(id)?.abort();
    const controller = new AbortController();
    browseControllersRef.current.set(id, controller);

    setGroupStates((current) => ({
      ...current,
      [id]: {
        ...(current[id] ?? emptyGroupState()),
        page,
        loading: true,
        error: false,
      },
    }));

    void aidpKnowledgeService
      .listIngestedFiles(
        knowledgeBase.id,
        page,
        FILE_SCOPE_BROWSE_PAGE_SIZE,
        "",
        controller.signal
      )
      .then((response) => {
        if (controller.signal.aborted) return;
        const files = mapFiles(response.value ?? [], knowledgeBase);
        const total = response.total_count;
        const hasMore = Boolean(response.has_more);
        pagesRef.current[id] = {
          ...(pagesRef.current[id] ?? {}),
          [page]: { files, total, hasMore },
        };
        setGroupStates((current) => ({
          ...current,
          [id]: {
            files,
            page,
            total,
            hasMore,
            loaded: true,
            loading: false,
            error: false,
          },
        }));
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setGroupStates((current) => ({
          ...current,
          [id]: {
            ...(current[id] ?? emptyGroupState()),
            page,
            loading: false,
            error: true,
          },
        }));
      })
      .finally(() => {
        loadingKeysRef.current.delete(requestKey);
        if (browseControllersRef.current.get(id) === controller) {
          browseControllersRef.current.delete(id);
        }
      });
  }, []);

  const executeSearch = useCallback((query: string) => {
    const generation = ++searchGenerationRef.current;
    searchControllerRef.current?.abort();
    const controller = new AbortController();
    searchControllerRef.current = controller;
    setSearchResults({});
    setSearchSettled(false);
    setSearchHasSuccess(false);

    const queue = [...groupsRef.current];
    let successes = 0;
    const worker = async () => {
      while (queue.length > 0) {
        if (
          controller.signal.aborted ||
          generation !== searchGenerationRef.current
        ) {
          return;
        }
        const knowledgeBase = queue.shift();
        if (!knowledgeBase) return;
        try {
          const response = await aidpKnowledgeService.listIngestedFiles(
            knowledgeBase.id,
            1,
            SEARCH_PAGE_SIZE,
            query,
            controller.signal
          );
          if (
            controller.signal.aborted ||
            generation !== searchGenerationRef.current
          ) {
            return;
          }
          successes += 1;
          const files = mapFiles(response.value ?? [], knowledgeBase);
          if (files.length > 0) {
            setSearchResults((current) => ({
              ...current,
              [knowledgeBase.id]: {
                files,
                hasMore: Boolean(response.has_more),
              },
            }));
          }
        } catch {
          // Search failures are intentionally silent.
        }
      }
    };

    const workerCount = Math.min(SEARCH_CONCURRENCY, queue.length);
    void Promise.all(Array.from({ length: workerCount }, () => worker())).then(
      () => {
        if (
          controller.signal.aborted ||
          generation !== searchGenerationRef.current
        ) {
          return;
        }
        setSearchSettled(true);
        setSearchHasSuccess(successes > 0);
      }
    );
  }, []);

  useEffect(() => {
    if (!enabled) return;
    if (
      initializedKeyRef.current === groupsKey &&
      initializedReloadRef.current === reloadToken
    ) {
      return;
    }
    initializedKeyRef.current = groupsKey;
    initializedReloadRef.current = reloadToken;
    abortBrowse();
    pagesRef.current = {};
    setGroupStates(
      Object.fromEntries(groups.map((group) => [group.id, emptyGroupState()]))
    );
    setSearchResults({});
    setSearchSettled(false);
    setSearchHasSuccess(false);
    const first = groups[0];
    if (first) loadGroup(first.id, 1);
  }, [enabled, groups, groupsKey, reloadToken, abortBrowse, loadGroup]);

  useEffect(() => {
    if (!enabled) return;
    const query = searchTerm.trim();
    if (query.length < SEARCH_MIN_LENGTH) {
      abortSearch();
      return;
    }
    abortSearch();
    const timer = window.setTimeout(
      () => executeSearch(query),
      SEARCH_DEBOUNCE_MS
    );
    return () => window.clearTimeout(timer);
  }, [enabled, searchTerm, reloadToken, groupsKey, abortSearch, executeSearch]);

  useEffect(
    () => () => {
      abortBrowse();
      abortSearch();
    },
    [abortBrowse, abortSearch]
  );

  const reload = useCallback(() => {
    abortBrowse();
    abortSearch();
    pagesRef.current = {};
    setGroupStates({});
    setSearchResults({});
    setSearchSettled(false);
    setSearchHasSuccess(false);
    setReloadToken((value) => value + 1);
  }, [abortBrowse, abortSearch]);

  return {
    groups,
    groupStates,
    browsePageSize: FILE_SCOPE_BROWSE_PAGE_SIZE,
    loadGroup,
    reload,
    searchActive: enabled && searchTerm.trim().length >= SEARCH_MIN_LENGTH,
    searchResults,
    searchSettled,
    searchHasSuccess,
  };
}
