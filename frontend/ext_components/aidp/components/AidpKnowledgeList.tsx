import React, { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button, Input, Pagination, Tooltip } from "antd";
import {
  BookOpen,
  CircleOff,
  Eye,
  FolderOpen,
  Glasses,
  PencilRuler,
  Search,
  SquarePen,
  Trash2,
} from "lucide-react";
import { PlusOutlined, ReloadOutlined } from "@ant-design/icons";

import type { AidpKnowledgeBaseItem } from "@/types/agentConfig";
import { useGroupList } from "@/hooks/group/useGroupList";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { Can } from "@/components/permission/Can";

interface AidpKnowledgeListProps {
  kbs: AidpKnowledgeBaseItem[];
  activeKbId: string | null;
  isLoading: boolean;
  total: number;
  /** True when `total` came from AIDP Count API. */
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

const permissionIcon = (permission?: string) => {
  const props = { size: 13, className: "text-gray-500" };
  switch (permission) {
    case "EDIT":
      return <PencilRuler {...props} />;
    case "READ_ONLY":
      return <Eye {...props} />;
    case "PRIVATE":
      return <Glasses {...props} />;
    default:
      return <CircleOff {...props} />;
  }
};

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
  const [searchKeyword, setSearchKeyword] = useState("");

  const { user } = useAuthorizationContext();
  const tenantId = user?.tenantId ?? null;
  const { data: groupListData } = useGroupList(tenantId);
  const groupById = useMemo(() => {
    const map = new Map<number, string>();
    (groupListData?.groups ?? []).forEach((group) => {
      map.set(group.group_id, group.group_name);
    });
    return map;
  }, [groupListData]);

  const displayedKbs = useMemo(() => {
    const keyword = searchKeyword.trim().toLowerCase();
    return [...kbs]
      .filter((kb) => {
        if (!keyword) return true;
        return [kb.kds_name, kb.description]
          .filter(Boolean)
          .some((value) => value!.toLowerCase().includes(keyword));
      })
      .sort((a, b) => {
        const aTime = Date.parse(a.updated_at || a.created_at || "") || 0;
        const bTime = Date.parse(b.updated_at || b.created_at || "") || 0;
        return bTime - aTime;
      });
  }, [kbs, searchKeyword]);

  const getGroupNames = (groupIds?: number[]) =>
    (groupIds ?? [])
      .map((id) => groupById.get(id))
      .filter((name): name is string => Boolean(name));

  const permissionLabel = (permission?: string) =>
    t(`knowledgeBase.ingroup.permission.${permission || "DEFAULT"}`);

  const renderStatusTag = (kb: AidpKnowledgeBaseItem) => {
    const isUnavailable =
      kb.resource_status === "UNAVAILABLE" || kb.resource_status === "ORPHANED";
    if (isUnavailable) {
      return (
        <span className="inline-flex items-center rounded-full border border-gray-200 bg-gray-50 px-2.5 py-1 text-xs font-medium text-gray-600">
          {t("aidpKnowledge.kbUnavailable")}
        </span>
      );
    }
    if (kb.permission === "READ_ONLY") {
      return (
        <span className="inline-flex items-center rounded-full border border-gray-200 bg-gray-50 px-2.5 py-1 text-xs font-medium text-gray-600">
          {t("aidpKnowledge.kbReadOnly")}
        </span>
      );
    }
    return null;
  };

  const renderKnowledgeCard = (kb: AidpKnowledgeBaseItem) => {
    const isActive = activeKbId === kb.kds_id;
    const isUnavailable =
      kb.resource_status === "UNAVAILABLE" || kb.resource_status === "ORPHANED";
    const canModify = kb.permission === "EDIT" && !isUnavailable;
    const groupNames = getGroupNames(kb.group_ids);
    const documentCount = kb.document_count ?? 0;
    const chunkCount = kb.chunk_count ?? 0;
    const permission = kb.ingroup_permission || "PRIVATE";

    return (
      <article
        key={kb.kds_id}
        data-knowledge-base-row
        role="button"
        tabIndex={0}
        className={`group flex min-h-[220px] cursor-pointer flex-col rounded-2xl border bg-white p-5 shadow-sm transition hover:-translate-y-0.5 hover:shadow-md ${
          isActive
            ? "border-blue-500 ring-2 ring-blue-100"
            : "border-gray-200 hover:border-blue-200"
        }`}
        onClick={() => onSelect(kb)}
        onKeyDown={(event) => {
          if (event.target !== event.currentTarget) return;
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            onSelect(kb);
          }
        }}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 items-center gap-3">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-blue-50 text-blue-600">
              <FolderOpen className="h-5 w-5" />
            </div>
            <div className="min-w-0">
              <h3
                className="truncate text-base font-semibold text-gray-900"
                title={kb.kds_name}
              >
                {kb.kds_name}
              </h3>
              <span className="mt-1 block truncate text-xs text-gray-400">
                AIDP
              </span>
            </div>
          </div>

          <div className="flex shrink-0 items-center gap-0.5 opacity-70 transition group-hover:opacity-100">
            {canModify && (
              <Tooltip title={t("common.edit")}>
                <Button
                  type="text"
                  size="small"
                  aria-label={t("common.edit")}
                  icon={<SquarePen className="h-4 w-4" />}
                  onClick={(event) => {
                    event.stopPropagation();
                    onEdit(kb);
                  }}
                />
              </Tooltip>
            )}
            {canModify && (
              <Tooltip title={t("common.delete")}>
                <Button
                  type="text"
                  danger
                  size="small"
                  aria-label={t("common.delete")}
                  icon={<Trash2 className="h-4 w-4" />}
                  onClick={(event) => {
                    event.stopPropagation();
                    onDelete(kb);
                  }}
                />
              </Tooltip>
            )}
          </div>
        </div>

        <p className="mt-4 line-clamp-2 min-h-10 text-sm leading-5 text-gray-500">
          {kb.description?.trim() || t("knowledgeBase.description.default")}
        </p>

        <div className="mt-4 flex flex-wrap content-start gap-2">
          <span className="inline-flex items-center rounded-full bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-700">
            {t("knowledgeBase.tag.documents", { count: documentCount })}
          </span>
          <span className="inline-flex items-center rounded-full bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-700">
            {t("knowledgeBase.tag.chunks", { count: chunkCount })}
          </span>
          {kb.embedding_model && kb.embedding_model !== "default" && (
            <span
              className="inline-flex max-w-full items-center truncate rounded-full bg-purple-50 px-2.5 py-1 text-xs font-medium text-purple-700"
              title={kb.embedding_model}
            >
              {kb.embedding_model}
            </span>
          )}
          {kb.is_multimodal && (
            <span className="inline-flex items-center rounded-full bg-red-50 px-2.5 py-1 text-xs font-medium text-red-700">
              multimodal
            </span>
          )}
          {renderStatusTag(kb)}
          <Can permission="group:read">
            {permission === "PRIVATE" ? (
              <span className="inline-flex items-center gap-1 rounded-full border border-gray-200 bg-gray-50 px-2.5 py-1 text-xs font-medium text-gray-600">
                {permissionIcon(permission)}
                {permissionLabel(permission)}
              </span>
            ) : (
              groupNames.slice(0, 2).map((groupName) => (
                <span
                  key={groupName}
                  className="inline-flex max-w-full items-center truncate rounded-full border border-blue-200 bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-700"
                  title={groupName}
                >
                  {groupName}
                </span>
              ))
            )}
          </Can>
        </div>

        <div className="mt-auto flex items-center justify-between border-t border-gray-100 pt-4 text-xs text-gray-400">
          <span>
            {t("knowledgeBase.tag.updatedAt", {
              date:
                kb.updated_at || kb.created_at
                  ? new Date(
                      kb.updated_at || kb.created_at || ""
                    ).toLocaleDateString()
                  : t("aidpKnowledge.createdAtUnknown"),
            })}
          </span>
          <span className="font-medium text-gray-500">
            {permissionLabel(permission)}
          </span>
        </div>
      </article>
    );
  };

  const effectiveTotal = totalReliable
    ? total
    : hasMore
      ? currentPage * pageSize + 1
      : currentPage * pageSize;

  return (
    <div className="flex h-full min-h-0 w-full flex-col overflow-hidden rounded-2xl bg-white">
      <div className="shrink-0 px-6 pb-4 pt-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex min-w-0 items-center gap-3">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-blue-100 text-blue-600">
              <BookOpen className="h-5 w-5" />
            </div>
            <div className="min-w-0">
              <h1 className="truncate text-2xl font-semibold tracking-tight text-gray-900">
                {t("knowledgeBase.page.title")}
              </h1>
              <p className="mt-1 text-sm text-gray-500">
                {t("knowledgeBase.page.description")}
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="primary"
              className="!h-10 !rounded-lg !px-4"
              onClick={onCreateNew}
              icon={<PlusOutlined />}
            >
              {t("knowledgeBase.button.create")}
            </Button>
            <Tooltip title={t("aidpKnowledge.refresh")}>
              <Button
                aria-label={t("aidpKnowledge.refresh")}
                className="!h-10 !w-10 !rounded-lg !p-0"
                onClick={onRefresh}
                icon={<ReloadOutlined spin={isLoading} />}
              />
            </Tooltip>
          </div>
        </div>

        <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-base font-semibold text-gray-900">
            {t("knowledgeBase.page.all")}
            <span className="ml-2 text-sm font-normal text-gray-400">
              {t("knowledgeBase.page.count", { count: total })}
            </span>
          </h2>
          <Input
            size="large"
            placeholder={t("knowledgeBase.search.placeholder")}
            prefix={<Search className="h-4 w-4 text-gray-400" />}
            value={searchKeyword}
            onChange={(event) => setSearchKeyword(event.target.value)}
            className="h-10 min-w-[240px] max-w-[420px] flex-1 !rounded-lg"
            allowClear
          />
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden px-6 pb-6">
        {isLoading && kbs.length === 0 ? (
          <div className="py-10 text-center text-sm text-gray-400">
            Loading...
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <button
              type="button"
              data-knowledge-base-row
              className="group flex min-h-[220px] flex-col items-center justify-center rounded-2xl border border-dashed border-blue-300 bg-blue-50/40 p-6 text-center transition hover:border-blue-500 hover:bg-blue-50"
              onClick={onCreateNew}
            >
              <span className="flex h-12 w-12 items-center justify-center rounded-full bg-blue-100 text-2xl font-light text-blue-600 transition group-hover:scale-105">
                +
              </span>
              <span className="mt-4 text-base font-semibold text-blue-700">
                {t("knowledgeBase.card.create")}
              </span>
              <span className="mt-1 text-sm text-blue-500">
                {t("knowledgeBase.card.createDescription")}
              </span>
            </button>
            {displayedKbs.map(renderKnowledgeCard)}
          </div>
        )}

        {!isLoading && displayedKbs.length === 0 && kbs.length > 0 && (
          <div className="py-10 text-center text-sm text-gray-400">
            {t("knowledgeBase.list.noResults")}
          </div>
        )}
        {!isLoading && displayedKbs.length === 0 && kbs.length === 0 && (
          <div className="py-10 text-center text-sm text-gray-400">
            {t("aidpKnowledge.listEmpty")}
          </div>
        )}
      </div>

      {kbs.length > 0 && (
        <div className="flex shrink-0 justify-center border-t border-gray-100 px-6 py-4">
          <Pagination
            current={currentPage}
            pageSize={pageSize}
            total={effectiveTotal || 1}
            onChange={onPageChange}
            showSizeChanger={false}
            simple={!totalReliable}
            showTotal={
              totalReliable
                ? (count) => t("aidpKnowledge.showTotal", { count })
                : undefined
            }
            size="small"
          />
        </div>
      )}
    </div>
  );
};

export default AidpKnowledgeList;
