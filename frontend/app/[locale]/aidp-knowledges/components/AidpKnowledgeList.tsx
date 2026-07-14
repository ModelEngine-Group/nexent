import React, { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { Button, Pagination, Tooltip } from "antd";
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
    <div className="w-full h-full bg-white border border-gray-200 rounded-md flex flex-col overflow-hidden">
      {/* Header */}
      <div className="p-4 border-b border-gray-200 shrink-0">
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
      <div className="flex-1 overflow-y-auto overflow-x-hidden">
        {displayedKbs.length > 0 ? (
          <div>
            {displayedKbs.map((kb) => {
              const isActive = activeKbId === kb.kds_id;

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
                      <p
                        className="text-sm font-medium text-gray-800 truncate"
                        title={kb.kds_name}
                      >
                        {kb.kds_name}
                      </p>
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

      {/* Server-side pagination — total from AIDP Count endpoint via backend */}
      {total > pageSize && (
        <div className="shrink-0 px-4 py-3 border-t border-gray-200 flex justify-center">
          <Pagination
            current={currentPage}
            pageSize={pageSize}
            total={total}
            onChange={onPageChange}
            showSizeChanger={false}
            size="small"
          />
        </div>
      )}
    </div>
  );
};

export default AidpKnowledgeList;
