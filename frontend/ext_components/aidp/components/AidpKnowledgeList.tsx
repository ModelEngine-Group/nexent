import React, { useMemo } from "react";
import { useTranslation } from "react-i18next";

import {
  Button,
  Checkbox,
  Input,
  Popover,
  Segmented,
  Table,
  Tag,
  Tooltip,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  AppstoreOutlined,
  PlusOutlined,
  ReloadOutlined,
  SearchOutlined,
  SettingOutlined,
  TableOutlined,
} from "@ant-design/icons";
import { SquarePen, Trash2 } from "lucide-react";

import type { AidpKnowledgeBaseItem } from "@/types/agentConfig";
import {
  AIDP_UNKNOWN_VALUE,
  formatAidpCapacity,
  formatAidpCreator,
  formatAidpDateTime,
  formatAidpDocumentCount,
  normalizeAidpKbType,
} from "@/lib/aidpKnowledgeDisplay";
import { useGroupList } from "@/hooks/group/useGroupList";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { Can } from "@/components/permission/Can";
import AidpKnowledgeGuide from "./AidpKnowledgeGuide";
import AidpPagination from "./AidpPagination";

/** Overview presentation modes. Cards are the default. */
export type AidpKbViewMode = "cards" | "table";

/** Every column the overview can render. */
export type AidpKbColumnKey =
  | "name"
  | "type"
  | "description"
  | "documents"
  | "capacity"
  | "creator"
  | "created_at"
  | "actions";

/** Columns the user cannot hide: the entry point and the row actions. */
export const AIDP_KB_REQUIRED_COLUMNS: AidpKbColumnKey[] = ["name", "actions"];

/** Default visible column set, used on first render and by "restore". */
export const AIDP_KB_DEFAULT_COLUMNS: AidpKbColumnKey[] = [
  "name",
  "type",
  "description",
  "documents",
  "capacity",
  "creator",
  "created_at",
  "actions",
];

/** Column labels shared by the table header and the visibility setting. */
const COLUMN_LABEL_KEYS: Record<AidpKbColumnKey, string> = {
  name: "aidpKnowledge.columnName",
  type: "aidpKnowledge.columnType",
  description: "aidpKnowledge.columnDescription",
  documents: "aidpKnowledge.columnDocuments",
  capacity: "aidpKnowledge.columnCapacity",
  creator: "aidpKnowledge.columnCreator",
  created_at: "aidpKnowledge.columnCreatedAt",
  actions: "aidpKnowledge.columnActions",
};

interface AidpKnowledgeListProps {
  kbs: AidpKnowledgeBaseItem[];
  isLoading: boolean;
  /** True when the last list request failed; drives the failure state. */
  loadFailed: boolean;
  total: number;
  /** True when `total` came from AIDP Count API (reliable). When false we
   *  show a simple prev/next pagination without "共 N 条". */
  totalReliable: boolean;
  hasMore: boolean;
  currentPage: number;
  pageSize: number;
  /** Raw search box value. The parent debounces it before querying, so this is
   *  intentionally the un-debounced text the user is currently typing. */
  keyword: string;
  viewMode: AidpKbViewMode;
  visibleColumns: AidpKbColumnKey[];
  onKeywordChange: (value: string) => void;
  onPageChange: (page: number) => void;
  onViewModeChange: (mode: AidpKbViewMode) => void;
  onVisibleColumnsChange: (columns: AidpKbColumnKey[]) => void;
  onSelect: (kb: AidpKnowledgeBaseItem) => void;
  onRefresh: () => void;
  onCreateNew: () => void;
  onEdit: (kb: AidpKnowledgeBaseItem) => void;
  onDelete: (kb: AidpKnowledgeBaseItem) => void;
  onRetry: () => void;
}

const AidpKnowledgeList: React.FC<AidpKnowledgeListProps> = ({
  kbs,
  isLoading,
  loadFailed,
  total,
  totalReliable,
  hasMore,
  currentPage,
  pageSize,
  keyword,
  viewMode,
  visibleColumns,
  onKeywordChange,
  onPageChange,
  onViewModeChange,
  onVisibleColumnsChange,
  onSelect,
  onRefresh,
  onCreateNew,
  onEdit,
  onDelete,
  onRetry,
}) => {
  const { t } = useTranslation();

  // Load groups for the current tenant so we can render group_ids as names.
  // ``useAuthorizationContext`` is the right hook here (the similarly-named
  // ``useAuthenticationContext`` carries only ``session`` — no ``user`` object).
  const { user } = useAuthorizationContext();
  const tenantId = user?.tenantId ?? null;
  const { data: groupListData } = useGroupList(tenantId);
  const groupById = useMemo(() => {
    const map = new Map<number, string>();
    (groupListData?.groups ?? []).forEach((g) => {
      map.set(g.group_id, g.group_name);
    });
    return map;
  }, [groupListData]);

  // Convert group ids to names, skipping any ids that don't resolve
  // (e.g. the group was deleted or the list is not yet loaded). Aligned
  // with the local-knowledge-base list renderer.
  const getGroupNames = (groupIds: number[] | undefined): string[] => {
    if (!Array.isArray(groupIds) || groupIds.length === 0) return [];
    return groupIds
      .map((id) => groupById.get(id))
      .filter(
        (name): name is string => typeof name === "string" && name.length > 0
      );
  };

  // Sort alphabetically by name
  const displayedKbs = useMemo(() => {
    return [...kbs].sort((a, b) =>
      (a.kds_name || "").localeCompare(b.kds_name || "")
    );
  }, [kbs]);

  const isRowUnavailable = (kb: AidpKnowledgeBaseItem) =>
    kb.resource_status === "UNAVAILABLE" || kb.resource_status === "ORPHANED";

  // Only EDIT-level callers may modify the KB or its files.
  const canModify = (kb: AidpKnowledgeBaseItem) =>
    kb.permission === "EDIT" && !isRowUnavailable(kb);

  const renderKbTypeTag = (kb: AidpKnowledgeBaseItem) => {
    const type = normalizeAidpKbType(kb.is_private);
    if (type === "personal") {
      return <Tag color="blue">{t("aidpKnowledge.kbTypePersonal")}</Tag>;
    }
    if (type === "enterprise") {
      return <Tag color="geekblue">{t("aidpKnowledge.kbTypeEnterprise")}</Tag>;
    }
    return <Tag>{AIDP_UNKNOWN_VALUE}</Tag>;
  };

  const renderStatusTags = (kb: AidpKnowledgeBaseItem) => (
    <>
      {isRowUnavailable(kb) && (
        <Tag color="default">{t("aidpKnowledge.kbUnavailable")}</Tag>
      )}
      {kb.permission === "READ_ONLY" && !isRowUnavailable(kb) && (
        <Tag color="default">{t("aidpKnowledge.kbReadOnly")}</Tag>
      )}
    </>
  );

  const renderGroupTags = (kb: AidpKnowledgeBaseItem) => (
    <Can permission="group:read">
      {kb.ingroup_permission !== "PRIVATE" &&
        getGroupNames(kb.group_ids).map((groupName, idx) => (
          <Tag key={idx} color="blue">
            {groupName}
          </Tag>
        ))}
    </Can>
  );

  const renderRowActions = (kb: AidpKnowledgeBaseItem) => (
    <div className="flex items-center gap-1 justify-end">
      {canModify(kb) && (
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
      {canModify(kb) && (
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
  );

  const renderCards = () => (
    <div className="p-4 grid gap-3 grid-cols-1 sm:grid-cols-2 xl:grid-cols-3">
      {displayedKbs.map((kb) => (
        <div
          key={kb.kds_id}
          role="button"
          tabIndex={0}
          onClick={() => onSelect(kb)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              onSelect(kb);
            }
          }}
          className="border border-gray-200 rounded-md p-3 hover:border-blue-400 hover:shadow-sm transition-all cursor-pointer flex flex-col"
        >
          <div className="flex items-start justify-between gap-2">
            <p
              className="min-w-0 flex-1 truncate text-sm font-medium text-gray-800"
              title={kb.kds_name}
            >
              {kb.kds_name}
            </p>
            {renderRowActions(kb)}
          </div>
          <div className="mt-2 flex items-center gap-1 flex-wrap">
            {renderKbTypeTag(kb)}
            {renderStatusTags(kb)}
          </div>
          <p
            className="mt-2 text-xs text-gray-500 truncate"
            title={kb.description || undefined}
          >
            {kb.description?.trim() ? kb.description : AIDP_UNKNOWN_VALUE}
          </p>
          <div className="mt-3 flex items-center gap-1 flex-wrap">
            <Tag>
              {t("aidpKnowledge.cardDocuments", {
                count: formatAidpDocumentCount(
                  kb.document_count,
                  kb.document_count_reliable
                ),
              })}
            </Tag>
            <Tag>
              {t("aidpKnowledge.cardCapacity", {
                value: formatAidpCapacity(kb.current_cap),
              })}
            </Tag>
            {renderGroupTags(kb)}
          </div>
          <div className="mt-2 flex items-center justify-between text-xs text-gray-400">
            <span className="truncate">{formatAidpCreator(kb.user_name)}</span>
            <span>{formatAidpDateTime(kb.created_at)}</span>
          </div>
        </div>
      ))}
    </div>
  );

  const renderTable = () => {
    const allColumns: Record<
      AidpKbColumnKey,
      ColumnsType<AidpKnowledgeBaseItem>[number]
    > = {
      name: {
        title: t("aidpKnowledge.columnName"),
        dataIndex: "kds_name",
        key: "name",
        render: (_value, kb) => (
          <span className="font-medium text-gray-800 break-all">
            {kb.kds_name}
          </span>
        ),
      },
      type: {
        title: t("aidpKnowledge.columnType"),
        key: "type",
        width: 110,
        render: (_value, kb) => renderKbTypeTag(kb),
      },
      description: {
        title: t("aidpKnowledge.columnDescription"),
        dataIndex: "description",
        key: "description",
        ellipsis: true,
        render: (value: string | undefined) =>
          value?.trim() ? value : AIDP_UNKNOWN_VALUE,
      },
      documents: {
        title: t("aidpKnowledge.columnDocuments"),
        key: "documents",
        width: 90,
        render: (_value, kb) =>
          formatAidpDocumentCount(
            kb.document_count,
            kb.document_count_reliable
          ),
      },
      capacity: {
        title: t("aidpKnowledge.columnCapacity"),
        key: "capacity",
        width: 110,
        render: (_value, kb) => formatAidpCapacity(kb.current_cap),
      },
      creator: {
        title: t("aidpKnowledge.columnCreator"),
        key: "creator",
        width: 130,
        render: (_value, kb) => formatAidpCreator(kb.user_name),
      },
      created_at: {
        title: t("aidpKnowledge.columnCreatedAt"),
        key: "created_at",
        width: 130,
        render: (_value, kb) => formatAidpDateTime(kb.created_at),
      },
      actions: {
        title: t("aidpKnowledge.columnActions"),
        key: "actions",
        width: 90,
        align: "right",
        render: (_value, kb) => renderRowActions(kb),
      },
    };

    // The required columns always render; the rest follow the column setting.
    const activeKeys = AIDP_KB_DEFAULT_COLUMNS.filter(
      (key) =>
        AIDP_KB_REQUIRED_COLUMNS.includes(key) || visibleColumns.includes(key)
    );

    return (
      <Table<AidpKnowledgeBaseItem>
        rowKey="kds_id"
        size="small"
        columns={activeKeys.map((key) => allColumns[key])}
        dataSource={displayedKbs}
        pagination={false}
        onRow={(kb) => ({
          onClick: () => onSelect(kb),
          style: { cursor: "pointer" },
        })}
      />
    );
  };

  const renderEmptyState = () => (
    <div className="p-8 text-center text-gray-500 text-sm">
      {keyword.trim()
        ? t("aidpKnowledge.searchEmpty")
        : t("aidpKnowledge.listEmpty")}
    </div>
  );

  const renderFailedState = () => (
    <div className="p-8 text-center">
      <p className="text-sm text-gray-500">
        {t("aidpKnowledge.listLoadFailed")}
      </p>
      <Button className="mt-3" size="small" onClick={onRetry}>
        {t("aidpKnowledge.retry")}
      </Button>
    </div>
  );

  const renderBody = () => {
    if (isLoading && displayedKbs.length === 0) {
      return (
        <div className="p-8 text-center text-gray-400 text-sm">
          {t("aidpKnowledge.listLoading")}
        </div>
      );
    }
    if (loadFailed && displayedKbs.length === 0) {
      return renderFailedState();
    }
    if (displayedKbs.length === 0) {
      return renderEmptyState();
    }
    return viewMode === "cards" ? renderCards() : renderTable();
  };

  const columnSettingContent = (
    <div className="flex flex-col gap-1">
      <Checkbox.Group
        value={visibleColumns}
        onChange={(values) =>
          onVisibleColumnsChange(values as AidpKbColumnKey[])
        }
        className="flex flex-col gap-1"
      >
        {AIDP_KB_DEFAULT_COLUMNS.map((key) => (
          <Checkbox
            key={key}
            value={key}
            disabled={AIDP_KB_REQUIRED_COLUMNS.includes(key)}
          >
            {t(COLUMN_LABEL_KEYS[key])}
          </Checkbox>
        ))}
      </Checkbox.Group>
      <Button
        type="link"
        size="small"
        className="px-0"
        onClick={() => onVisibleColumnsChange(AIDP_KB_DEFAULT_COLUMNS)}
      >
        {t("aidpKnowledge.columnSettingsRestore")}
      </Button>
    </div>
  );

  return (
    <div className="w-full flex flex-col gap-3">
      {/* Guide sits above the overview card and owns its own collapse state. */}
      <AidpKnowledgeGuide />

      <div className="w-full bg-white border border-gray-200 rounded-md overflow-hidden">
        {/* Header */}
        <div className="p-4 border-b border-gray-200">
          <div className="flex items-center justify-between gap-2 flex-wrap">
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

          <div className="mt-3 flex items-center gap-2 flex-wrap">
            <Input
              allowClear
              className="max-w-xs"
              placeholder={t("aidpKnowledge.searchPlaceholder")}
              prefix={<SearchOutlined className="text-gray-400" />}
              value={keyword}
              onChange={(e) => onKeywordChange(e.target.value)}
              size="small"
            />
            <Segmented
              size="small"
              value={viewMode}
              onChange={(value) => onViewModeChange(value as AidpKbViewMode)}
              options={[
                {
                  value: "cards",
                  label: t("aidpKnowledge.viewCards"),
                  icon: <AppstoreOutlined />,
                },
                {
                  value: "table",
                  label: t("aidpKnowledge.viewTable"),
                  icon: <TableOutlined />,
                },
              ]}
            />
            {/* Column visibility only affects the table view. */}
            {viewMode === "table" && (
              <Popover
                trigger="click"
                placement="bottomRight"
                content={columnSettingContent}
              >
                <Tooltip title={t("aidpKnowledge.columnSettings")}>
                  <Button icon={<SettingOutlined />} size="small" />
                </Tooltip>
              </Popover>
            )}
          </div>
        </div>

        {/* Body */}
        <div>{renderBody()}</div>

        {/* Server-side pagination; see AidpPagination for the fallback rule. */}
        {kbs.length > 0 && (
          <div className="px-4 py-3 border-t border-gray-200 flex justify-center">
            <AidpPagination
              currentPage={currentPage}
              pageSize={pageSize}
              total={total}
              totalReliable={totalReliable}
              hasMore={hasMore}
              onPageChange={onPageChange}
            />
          </div>
        )}
      </div>
    </div>
  );
};

export default AidpKnowledgeList;
