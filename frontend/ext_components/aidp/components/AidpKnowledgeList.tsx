import React, { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { Button, Pagination, Tag, Tooltip } from "antd";
import {
  PlusOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import { SquarePen, Trash2 } from "lucide-react";

import type { AidpKnowledgeBaseItem } from "@/types/agentConfig";

interface AidpKnowledgeListProps {
  kbs: AidpKnowledgeBaseItem[];
  activeKbId: string | null;
  isLoading: boolean;
  total: number;
  /** True when `total` came from AIDP Count API (reliable). When false we
   *  show a simple prev/next pagination without "共 N 条". */
  totalReliable: boolean;
  hasMore: boolean;
  currentPage: number;
  pageSize: number;
  onPageChange: (page: number) => void;
  onSelect: (kb: AidpKnowledgeBaseItem) => void;
  onRefresh: () => void;
  onCreateNew: () => void;
  onEdit: (kb: AidpKnowledgeBaseItem) => void;
  onDelete: (kb: AidpKnowledgeBaseItem) => void;
}

const AidpKnowledgeList: React.FC<AidpKnowledgeListProps> = ({
  kbs,
  activeKbId,
  isLoading,
  total,
  totalReliable,
  hasMore,
  currentPage,
  pageSize,
  onPageChange,
  onSelect,
  onRefresh,
  onCreateNew,
  onEdit,
  onDelete,
}) => {
  const { t } = useTranslation();

  // Sort alphabetically by name
  const displayedKbs = useMemo(() => {
    return [...kbs].sort((a, b) =>
      (a.kds_name || "").localeCompare(b.kds_name || "")
    );
  }, [kbs]);

  return (
    <div className="w-full bg-white border border-gray-200 rounded-md overflow-hidden">
      {/* Header */}
      <div className="p-4 border-b border-gray-200">
        <div className="flex items-center justify-between gap-2">
          <h3 className="text-base font-semibold text-gray-800">
            {t("aidpKnowledge.kbListTitle")}
          </h3>
          <div className="flex items-center gap-2">
            <Button
              type="primary"
              onClick={onCreateNew}
              icon={<PlusOutlined />}
              size="small"
            >
              {t("aidpKnowledge.createKb")}
            </Button>
            <Tooltip title={t("aidpKnowledge.refresh")}>
              <Button
                icon={<ReloadOutlined spin={isLoading} />}
                onClick={onRefresh}
                size="small"
              />
            </Tooltip>
          </div>
        </div>
      </div>

      {/* List */}
      <div>
        {displayedKbs.length > 0 ? (
          <div>
            {displayedKbs.map((kb) => {
              const isActive = activeKbId === kb.kds_id;
              const isUnavailable =
                kb.resource_status === "UNAVAILABLE" ||
                kb.resource_status === "ORPHANED";
              // Only EDIT-level callers may modify the KB or its files.
              const canModify = kb.permission === "EDIT" && !isUnavailable;

              return (
                <div
                  key={kb.kds_id}
                  className="px-2 py-3 hover:bg-gray-50 cursor-pointer transition-colors border-t border-gray-100 first:border-t-0"
                  style={{
                    borderLeftWidth: "4px",
                    borderLeftStyle: "solid",
                    borderLeftColor: isActive ? "#3b82f6" : "transparent",
                    backgroundColor: isActive
                      ? "rgb(226, 240, 253)"
                      : undefined,
                  }}
                  onClick={() => onSelect(kb)}
                >
                  <div className="flex items-start justify-between">
                    <div className="flex-1 min-w-0 mr-2">
                      <div className="flex items-center gap-2 flex-wrap">
                        <p
                          className="text-sm font-medium text-gray-800 truncate"
                          title={kb.kds_name}
                        >
                          {kb.kds_name}
                        </p>
                        {isUnavailable && (
                          <Tag color="default">
                            {t("aidpKnowledge.kbUnavailable")}
                          </Tag>
                        )}
                        {kb.permission === "READ_ONLY" && !isUnavailable && (
                          <Tag color="default">
                            {t("aidpKnowledge.kbReadOnly")}
                          </Tag>
                        )}
                      </div>
                      {kb.description && (
                        <p className="text-xs text-gray-500 truncate mt-1">
                          {kb.description}
                        </p>
                      )}
                      <div className="flex items-center gap-2 mt-2 flex-wrap">
                        {kb.chunk_count !== undefined && (
                          <span className="inline-flex items-center px-2 py-0.5 rounded text-xs bg-gray-100 text-gray-600 border border-gray-200">
                            {t("aidpKnowledge.tagChunks", {
                              count: kb.chunk_count,
                            })}
                          </span>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-1 shrink-0">
                      {canModify && (
                        <Tooltip title={t("common.edit")}>
                          <Button
                            type="text"
                            icon={<SquarePen className="h-4 w-4" />}
                            onClick={(e) => {
                              e.stopPropagation();
                              onEdit(kb);
                            }}
                            size="small"
                          />
                        </Tooltip>
                      )}
                      {canModify && (
                        <Tooltip title={t("common.delete")}>
                          <Button
                            type="text"
                            danger
                            icon={<Trash2 className="h-4 w-4" />}
                            onClick={(e) => {
                              e.stopPropagation();
                              onDelete(kb);
                            }}
                            size="small"
                          />
                        </Tooltip>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="p-6 text-center text-gray-500 text-sm">
            {t("aidpKnowledge.listEmpty")}
          </div>
        )}
      </div>

      {/* Server-side pagination.
          AIDP exposes a dedicated Count API for KBs which the backend calls
          alongside the list request. When Count succeeds, `totalReliable`
          is true and we display the full pagination (page numbers +
          "共 N 条"). When Count fails (e.g. endpoint unavailable), we fall
          back to simple prev/next mode using `has_more`. */}
      {kbs.length > 0 && (() => {
        const effectiveTotal = totalReliable
          ? total
          : (hasMore
              ? currentPage * pageSize + 1
              : currentPage * pageSize);
        return (
          <div className="px-4 py-3 border-t border-gray-200 flex justify-center">
            <Pagination
              current={currentPage}
              pageSize={pageSize}
              total={effectiveTotal || 1}
              onChange={onPageChange}
              showSizeChanger={false}
              simple={!totalReliable}
              showTotal={
                totalReliable
                  ? (total) => t("aidpKnowledge.showTotal", { count: total })
                  : undefined
              }
              size="small"
            />
          </div>
        );
      })()}
    </div>
  );
};

export default AidpKnowledgeList;
