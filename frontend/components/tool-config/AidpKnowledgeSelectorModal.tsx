"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Button,
  Checkbox,
  Empty,
  Input,
  Modal,
  Pagination,
  Space,
  Spin,
  Tag,
  Typography,
  message,
} from "antd";
import { useTranslation } from "react-i18next";

import knowledgeBaseService from "@/services/knowledgeBaseService";
import type { AidpKnowledgeBaseItem } from "@/types/agentConfig";

const { Text } = Typography;

interface AidpKnowledgeSelectorModalProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: (selected: { datasetIds: string[]; displayNames: string[] }) => void;
  selectedDatasetIds: string[];
  serverUrl: string;
  apiKey: string;
  title?: string;
  maxSelect?: number;
}

const DEFAULT_PAGE_SIZE = 10;

export default function AidpKnowledgeSelectorModal({
  isOpen,
  onClose,
  onConfirm,
  selectedDatasetIds,
  serverUrl,
  apiKey,
  title,
  maxSelect = 10,
}: AidpKnowledgeSelectorModalProps) {
  const { t } = useTranslation("common");

  // Accumulate loaded items across all pages; replace when serverUrl/apiKey changes
  const [allLoadedItems, setAllLoadedItems] = useState<AidpKnowledgeBaseItem[]>([]);
  // Local selection state so toggling checkboxes does not auto-close the modal
  const [tempSelectedIds, setTempSelectedIds] = useState<string[]>([]);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const [total, setTotal] = useState(0);
  const [keyword, setKeyword] = useState("");
  const [loading, setLoading] = useState(false);

  // Persist display names for selected IDs even when they scroll off the loaded page
  const nameMap = useRef<Map<string, string>>(new Map());
  // Keep a ref to latest selectedDatasetIds to avoid stale closures in loadPage
  const selectedDatasetIdsRef = useRef<string[]>(selectedDatasetIds);
  useEffect(() => {
    selectedDatasetIdsRef.current = selectedDatasetIds;
  }, [selectedDatasetIds]);
  // Keep refs to latest credentials so loadPage can read them without
  // recreating the callback on every credential change.
  const serverUrlRef = useRef(serverUrl);
  const apiKeyRef = useRef(apiKey);
  useEffect(() => {
    serverUrlRef.current = serverUrl;
  }, [serverUrl]);
  useEffect(() => {
    apiKeyRef.current = apiKey;
  }, [apiKey]);

  // ------------------------------------------------------------------
  // Reset all state when modal opens
  // ------------------------------------------------------------------
  useEffect(() => {
    if (!isOpen) return;
    setAllLoadedItems([]);
    setTempSelectedIds(selectedDatasetIds);
    setPage(1);
    setPageSize(DEFAULT_PAGE_SIZE);
    setTotal(0);
    setKeyword("");
    nameMap.current = new Map();
  }, [isOpen]);

  // ------------------------------------------------------------------
  // Keep display names in sync with the parent's selectedDatasetIds
  // Handles: external removal (tool config panel deletes a KB → uncheck in modal)
  // ------------------------------------------------------------------
  useEffect(() => {
    if (!isOpen) return;
    const ids = new Set(selectedDatasetIds.map(String));
    // Prune nameMap of IDs that are no longer selected
    for (const id of nameMap.current.keys()) {
      if (!ids.has(id)) {
        nameMap.current.delete(id);
      }
    }
  }, [isOpen, selectedDatasetIds]);

  // ------------------------------------------------------------------
  // Load a single page from the API
  // ------------------------------------------------------------------
  const loadPage = useCallback(
    async (nextPage: number, nextPageSize: number) => {
      // Read latest credentials from refs to keep this callback's identity stable
      const currentServerUrl = serverUrlRef.current;
      const currentApiKey = apiKeyRef.current;
      if (!currentServerUrl || !currentApiKey) {
        setAllLoadedItems([]);
        setTotal(0);
        return;
      }

      setLoading(true);
      try {
        const result = await knowledgeBaseService.getAidpKnowledgeBases(
          currentServerUrl,
          currentApiKey,
          nextPage,
          nextPageSize
        );

        const items = result.value || [];
        const newTotal = result.total_count ?? items.length;

        // Read selectedDatasetIds from a ref to avoid dependency changes triggering re-fetch
        const currentSelectedIds = selectedDatasetIdsRef.current;

        if (nextPage === 1) {
          // Fresh load — replace the accumulated list
          setAllLoadedItems(items);
          // Always rebuild nameMap for this page's items with their names
          // This ensures we have display names even for non-selected items
          const nextNameMap = new Map<string, string>();
          for (const item of items) {
            const id = String(item.kds_id);
            const name = item.kds_name || id;
            // Keep previously stored name for still-selected IDs to avoid flicker
            const storedName = nameMap.current.get(id);
            nextNameMap.set(id, storedName ?? name);
          }
          nameMap.current = nextNameMap;
        } else {
          // Append page N > 1
          setAllLoadedItems((prev) => [...prev, ...items]);
          for (const item of items) {
            const id = String(item.kds_id);
            const name = item.kds_name || id;
            if (currentSelectedIds.includes(id) && !nameMap.current.has(id)) {
              nameMap.current.set(id, name);
            }
          }
        }

        setTotal(newTotal);
      } catch (error) {
        message.error(t("toolConfig.aidp.selector.loadFailed"));
        if (nextPage === 1) {
          setAllLoadedItems([]);
          setTotal(0);
        }
      } finally {
        setLoading(false);
      }
    },
    [t]
  );

  // ------------------------------------------------------------------
  // Trigger load when modal opens OR credentials change
  // ------------------------------------------------------------------
  const triggerLoad = useCallback(() => {
    setPage(1);
    // Read latest selectedDatasetIds from ref to avoid stale closure
    void loadPage(1, pageSize);
  }, [pageSize]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!isOpen) return;
    // Touch selectedDatasetIdsRef to ensure latest value is read inside loadPage
    void selectedDatasetIdsRef.current;
    triggerLoad();
  }, [isOpen, serverUrl, apiKey, selectedDatasetIds, triggerLoad]); // eslint-disable-line react-hooks/exhaustive-deps

  // ------------------------------------------------------------------
  // Reload on page / pageSize change
  // ------------------------------------------------------------------
  useEffect(() => {
    if (!isOpen) return;
    void loadPage(page, pageSize);
  }, [page, pageSize]); // eslint-disable-line react-hooks/exhaustive-deps

  // ------------------------------------------------------------------
  // Client-side keyword filter applied to the accumulated list
  // ------------------------------------------------------------------
  const filteredItems = useMemo(() => {
    const kw = keyword.trim().toLowerCase();
    if (!kw) return allLoadedItems;
    return allLoadedItems.filter((item) => {
      const n = String(item.kds_name || "").toLowerCase();
      const i = String(item.kds_id || "").toLowerCase();
      const d = String(item.description || "").toLowerCase();
      return n.includes(kw) || i.includes(kw) || d.includes(kw);
    });
  }, [allLoadedItems, keyword]);

  // ------------------------------------------------------------------
  // Selected IDs — always derived from the parent's prop (source of truth)
  // ------------------------------------------------------------------

  const handleToggle = (item: AidpKnowledgeBaseItem, checked: boolean) => {
    const id = String(item.kds_id);
    if (checked) {
      if (tempSelectedIds.length >= maxSelect) {
        message.warning(
          t("toolConfig.aidp.selector.maxSelect", { count: maxSelect })
        );
        return;
      }
      nameMap.current.set(id, item.kds_name || id);
      setTempSelectedIds((prev) => [...prev, id]);
    } else {
      nameMap.current.delete(id);
      setTempSelectedIds((prev) => prev.filter((sid) => sid !== id));
    }
  };

  const handleTagClose = (id: string) => {
    nameMap.current.delete(id);
    setTempSelectedIds((prev) => prev.filter((sid) => sid !== id));
  };

  const displayNames = tempSelectedIds.map((id) => nameMap.current.get(id) || id);

  return (
    <Modal
      title={title || t("toolConfig.aidp.selector.title")}
      open={isOpen}
      onCancel={onClose}
      onOk={() => {
        onConfirm({
          datasetIds: tempSelectedIds,
          displayNames,
        });
      }}
      width={920}
      okText={t("common.confirm")}
      cancelText={t("common.cancel")}
      okButtonProps={{ disabled: tempSelectedIds.length === 0 }}
    >
      <Space orientation="vertical" size={12} style={{ width: "100%" }}>
        <Input
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          placeholder={t("toolConfig.aidp.selector.searchPlaceholder")}
        />

        <div className="flex items-center justify-between">
          <Text type="secondary">
            {t("toolConfig.aidp.selector.selectedCount", {
              count: tempSelectedIds.length,
              max: maxSelect,
            })}
          </Text>
          <Button
            onClick={() => {
              setPage(1);
              void loadPage(1, pageSize);
            }}
          >
            {t("knowledgeBase.button.sync")}
          </Button>
        </div>

        {tempSelectedIds.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {tempSelectedIds.map((id) => (
              <Tag
                key={id}
                closable
                onClose={(e) => {
                  e.preventDefault();
                  handleTagClose(id);
                }}
              >
                {nameMap.current.get(id) || id}
              </Tag>
            ))}
          </div>
        )}

        <div style={{ minHeight: 420 }}>
          {loading && allLoadedItems.length === 0 ? (
            <div className="flex justify-center py-12">
              <Spin />
            </div>
          ) : filteredItems.length === 0 ? (
            <Empty description={t("toolConfig.aidp.selector.empty")} />
          ) : (
            <div className="divide-y divide-gray-100 rounded-md border border-gray-200 bg-white">
              {filteredItems.map((item) => {
                const id = String(item.kds_id);
                const checked = tempSelectedIds.includes(id);
                const disableUnchecked =
                  !checked && tempSelectedIds.length >= maxSelect;
                return (
                  <div key={id} className="px-4 py-3">
                    <div className="flex w-full items-start justify-between gap-4">
                      <div className="min-w-0 flex-1">
                        <div className="mb-1 flex items-center gap-2">
                          <Checkbox
                            checked={checked}
                            disabled={disableUnchecked}
                            onChange={(e) =>
                              handleToggle(item, e.target.checked)
                            }
                          >
                            {item.kds_name || id}
                          </Checkbox>
                          <Tag>{id}</Tag>
                        </div>
                        {item.description && (
                          <Text type="secondary">{item.description}</Text>
                        )}
                      </div>
                      <Space size={8}>
                        <Tag>
                          {t(
                            "toolConfig.aidp.selector.documentCount",
                            { count: item.document_count || 0 }
                          )}
                        </Tag>
                        <Tag>
                          {t("toolConfig.aidp.selector.chunkCount", {
                            count: item.chunk_count || 0,
                          })}
                        </Tag>
                      </Space>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        <div className="flex justify-end">
          <Pagination
            current={page}
            pageSize={pageSize}
            total={total}
            showSizeChanger
            onChange={(nextPage, nextPageSize) => {
              setPage(nextPage);
              setPageSize(nextPageSize);
            }}
          />
        </div>
      </Space>
    </Modal>
  );
}
