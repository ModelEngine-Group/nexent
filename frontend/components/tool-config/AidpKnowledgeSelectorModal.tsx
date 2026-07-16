"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Button,
  Checkbox,
  Empty,
  Input,
  Modal,
  Space,
  Spin,
  Tag,
  Typography,
  message,
} from "antd";
import { LeftOutlined, RightOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";

import log from "@/lib/logger";
import knowledgeBaseService from "@/services/knowledgeBaseService";
import type { AidpKnowledgeBaseItem } from "@/types/agentConfig";

const { Text } = Typography;

interface AidpKnowledgeSelectorModalProps {
  readonly isOpen: boolean;
  readonly onClose: () => void;
  readonly onConfirm: (selected: { datasetIds: string[]; displayNames: string[] }) => void;
  readonly selectedDatasetIds: string[];
  readonly title?: string;
  readonly maxSelect?: number;
}

const DEFAULT_PAGE_SIZE = 10;

export default function AidpKnowledgeSelectorModal({
  isOpen,
  onClose,
  onConfirm,
  selectedDatasetIds,
  title,
  maxSelect = 10,
}: AidpKnowledgeSelectorModalProps) {
  const { t } = useTranslation("common");

  const [currentPage, setCurrentPage] = useState(1);
  const [pageItems, setPageItems] = useState<AidpKnowledgeBaseItem[]>([]);
  const [nextLink, setNextLink] = useState<string | null>(null);
  const [keyword, setKeyword] = useState("");
  const [loading, setLoading] = useState(false);
  const [tempSelectedIds, setTempSelectedIds] = useState<string[]>([]);

  const nameMap = useRef<Map<string, string>>(new Map());
  const prevKeyword = useRef("");

  // ------------------------------------------------------------------
  // Reset all state when modal opens
  // ------------------------------------------------------------------
  useEffect(() => {
    if (!isOpen) return;
    setCurrentPage(1);
    setPageItems([]);
    setNextLink(null);
    setKeyword("");
    setTempSelectedIds(selectedDatasetIds);
    nameMap.current = new Map();
    prevKeyword.current = "";
  }, [isOpen]);

  // ------------------------------------------------------------------
  // Keep display names in sync with the parent's selectedDatasetIds
  // ------------------------------------------------------------------
  useEffect(() => {
    if (!isOpen) return;
    const ids = new Set(selectedDatasetIds.map(String));
    for (const id of nameMap.current.keys()) {
      if (!ids.has(id)) {
        nameMap.current.delete(id);
      }
    }
  }, [isOpen, selectedDatasetIds]);

  // ------------------------------------------------------------------
  // Fetch a single page (page 1 on open/credentials change; next/prev on nav)
  // ------------------------------------------------------------------
  const loadPage = useCallback(
    async (pageNum: number, nextUrl: string | null = null) => {
      setLoading(true);
      try {
        const result = await knowledgeBaseService.getAidpKnowledgeBases(
          pageNum,
          DEFAULT_PAGE_SIZE
        );

        const items: AidpKnowledgeBaseItem[] = result.value || [];

        if (nextUrl) {
          setNextLink(result.next_link ?? null);
        } else {
          setNextLink(result.next_link ?? null);
        }

        for (const item of items) {
          const id = String(item.kds_id);
          if (!nameMap.current.has(id)) {
            nameMap.current.set(id, item.kds_name || id);
          }
        }

        setPageItems(items);
        setCurrentPage(pageNum);
      } catch (error) {
        log.error("Failed to load AIDP knowledge bases:", error);
        message.error(t("toolConfig.aidp.selector.loadFailed"));
        setPageItems([]);
        setNextLink(null);
      } finally {
        setLoading(false);
      }
    },
    [t]
  );

  // ------------------------------------------------------------------
  // Load first page when modal opens
  // ------------------------------------------------------------------
  useEffect(() => {
    if (!isOpen) return;
    loadPage(1);
  }, [isOpen]); // eslint-disable-line react-hooks/exhaustive-deps

  // ------------------------------------------------------------------
  // Keyword filter (client-side on current page)
  // ------------------------------------------------------------------
  const filteredItems = useMemo(() => {
    const kw = keyword.trim().toLowerCase();
    if (!kw) return pageItems;
    return pageItems.filter((item) => {
      const n = String(item.kds_name || "").toLowerCase();
      const i = String(item.kds_id || "").toLowerCase();
      const d = String(item.description || "").toLowerCase();
      return n.includes(kw) || i.includes(kw) || d.includes(kw);
    });
  }, [pageItems, keyword]);

  // ------------------------------------------------------------------
  // Sync / Reload current page
  // ------------------------------------------------------------------
  const handleSync = () => {
    loadPage(currentPage);
  };

  // ------------------------------------------------------------------
  // Toggle selection
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

  const displayNames = tempSelectedIds.map(
    (id) => nameMap.current.get(id) || id
  );

  const renderRow = (item: AidpKnowledgeBaseItem) => {
    const id = String(item.kds_id);
    const checked = tempSelectedIds.includes(id);
    const disableUnchecked =
      !checked && tempSelectedIds.length >= maxSelect;
    return (
      <div key={id} className="px-4 py-3">
        <div className="flex w-full items-start justify-between gap-4 flex-wrap">
          <div className="min-w-0 flex-1">
            <div className="mb-1 flex items-start gap-2">
              <Checkbox
                id={`aidp-kb-${id}`}
                checked={checked}
                disabled={disableUnchecked}
                onChange={(e) => handleToggle(item, e.target.checked)}
                className="shrink-0 mt-0.5"
              />
              <Tag className="shrink-0">{id}</Tag>
              <label
                htmlFor={`aidp-kb-${id}`}
                className="cursor-pointer break-all leading-5 min-w-0"
              >
                {item.kds_name || id}
              </label>
            </div>
            {item.description && (
              <Text type="secondary" className="break-words">{item.description}</Text>
            )}
          </div>
        </div>
      </div>
    );
  };

  const renderListContent = () => {
    if (loading && pageItems.length === 0) {
      return (
        <div className="flex justify-center py-12">
          <Spin />
        </div>
      );
    }
    if (filteredItems.length === 0) {
      return <Empty description={t("toolConfig.aidp.selector.empty")} />;
    }
    return (
      <div className="divide-y divide-gray-100 rounded-md border border-gray-200 bg-white">
        {filteredItems.map(renderRow)}
      </div>
    );
  };

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
          onChange={(e) => {
            setKeyword(e.target.value);
          }}
          placeholder={t("toolConfig.aidp.selector.searchPlaceholder")}
        />

        <div className="flex items-center justify-between">
          <Text type="secondary">
            {t("toolConfig.aidp.selector.selectedCount", {
              count: tempSelectedIds.length,
              max: maxSelect,
            })}
          </Text>
          <Button onClick={handleSync}>
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
          {renderListContent()}
        </div>

        <div className="flex items-center justify-center gap-4">
          <Button
            icon={<LeftOutlined />}
            disabled={currentPage === 1 || loading}
            onClick={() => loadPage(currentPage - 1)}
          >
            {t("filePreview.pdf.previousPage")}
          </Button>
          <Text type="secondary">{currentPage}</Text>
          <Button
            icon={<RightOutlined />}
            disabled={!nextLink || loading}
            onClick={() => loadPage(currentPage + 1)}
          >
            {t("filePreview.pdf.nextPage")}
          </Button>
        </div>
      </Space>
    </Modal>
  );
}
