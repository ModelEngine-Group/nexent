"use client";

import React, { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  Button,
  Checkbox,
  ConfigProvider,
  Dropdown,
  Input,
  type MenuProps,
  Popover,
  Segmented,
  Table,
  Tag,
  Tooltip,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  AppstoreOutlined,
  ClockCircleOutlined,
  DatabaseOutlined,
  EllipsisOutlined,
  FileAddOutlined,
  FileTextOutlined,
  ReloadOutlined,
  SearchOutlined,
  SettingOutlined,
  TableOutlined,
} from "@ant-design/icons";
import { Trash2 } from "lucide-react";

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
import { aidpKnowledgeVisualTheme } from "./aidpKnowledgeVisualTheme";
import styles from "./AidpKnowledgeVisuals.module.css";

/** Keep the compact card date in the UCD year-month-day format. */
function formatCardDate(value: unknown): string {
  if (formatAidpDateTime(value) === AIDP_UNKNOWN_VALUE)
    return AIDP_UNKNOWN_VALUE;
  return new Date(value as string).toLocaleDateString("sv-SE");
}

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
  loadFailed: boolean;
  total: number;
  totalReliable: boolean;
  hasMore: boolean;
  currentPage: number;
  pageSize: number;
  keyword: string;
  viewMode: AidpKbViewMode;
  visibleColumns: AidpKbColumnKey[];
  onKeywordChange: (value: string) => void;
  onPageChange: (page: number) => void;
  onPageSizeChange: (pageSize: number) => void;
  onViewModeChange: (mode: AidpKbViewMode) => void;
  onVisibleColumnsChange: (columns: AidpKbColumnKey[]) => void;
  onSelect: (kb: AidpKnowledgeBaseItem) => void;
  onRefresh: () => void;
  onCreateNew: () => void;
  onImport: (kb: AidpKnowledgeBaseItem) => void;
  onDelete: (kb: AidpKnowledgeBaseItem) => void;
  onRetry: () => void;
}

interface ResizableTitleProps extends Omit<
  React.ThHTMLAttributes<HTMLTableCellElement>,
  "onResize"
> {
  width?: number;
  onResize?: (width: number) => void;
}

const ResizableTitle: React.FC<ResizableTitleProps> = ({
  width,
  onResize,
  children,
  ...rest
}) => {
  const { t } = useTranslation();
  const isFixedColumn = Boolean(rest.className?.includes("ant-table-cell-fix"));
  const handlePointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!onResize || typeof width !== "number") return;
    event.preventDefault();
    event.stopPropagation();
    const startX = event.clientX;
    const startWidth = width;
    const handleMove = (moveEvent: PointerEvent) => {
      onResize(Math.max(88, startWidth + moveEvent.clientX - startX));
    };
    const handleUp = () => {
      window.removeEventListener("pointermove", handleMove);
      window.removeEventListener("pointerup", handleUp);
    };
    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerup", handleUp, { once: true });
  };

  return (
    <th
      {...rest}
      style={{
        ...rest.style,
        width,
        ...(isFixedColumn ? {} : { position: "relative" }),
      }}
    >
      {children}
      {onResize && (
        <div
          role="separator"
          aria-orientation="vertical"
          aria-label={t("aidpKnowledge.resizeColumn")}
          className="absolute right-0 top-0 z-10 h-full w-2 cursor-col-resize touch-none select-none after:absolute after:right-[3px] after:top-1/4 after:h-1/2 after:w-px after:bg-gray-300 hover:after:bg-blue-500"
          onPointerDown={handlePointerDown}
          onClick={(event) => event.stopPropagation()}
        />
      )}
    </th>
  );
};

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
  onPageSizeChange,
  onViewModeChange,
  onVisibleColumnsChange,
  onSelect,
  onRefresh,
  onCreateNew,
  onImport,
  onDelete,
  onRetry,
}) => {
  const { t } = useTranslation();
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
  const [columnWidths, setColumnWidths] = useState<Record<string, number>>({});

  const displayedKbs = useMemo(
    () =>
      [...kbs].sort((a, b) =>
        (a.kds_name || "").localeCompare(b.kds_name || "")
      ),
    [kbs]
  );

  const isRowUnavailable = (kb: AidpKnowledgeBaseItem) =>
    kb.resource_status === "UNAVAILABLE" || kb.resource_status === "ORPHANED";
  const canModify = (kb: AidpKnowledgeBaseItem) =>
    kb.permission === "EDIT" && !isRowUnavailable(kb);

  const getGroupNames = (ids: number[] | undefined) =>
    Array.isArray(ids)
      ? ids
          .map((id) => groupById.get(id))
          .filter((name): name is string => Boolean(name))
      : [];

  const renderScope = (kb: AidpKnowledgeBaseItem) => {
    const isPrivate = kb.ingroup_permission === "PRIVATE";
    const isShared =
      kb.ingroup_permission === "EDIT" || kb.ingroup_permission === "READ_ONLY";
    const type = normalizeAidpKbType(kb.is_private);
    const groupNames = isShared ? getGroupNames(kb.group_ids) : [];

    return (
      <div className="flex min-w-0 flex-wrap items-center gap-1.5">
        {isPrivate ? (
          <Tag color="blue" className="mr-0">
            {t("aidpKnowledge.scopePrivate")}
          </Tag>
        ) : isShared ? (
          <>
            <Tag color="geekblue" className="mr-0">
              {t("aidpKnowledge.scopeShared")}
            </Tag>
            <Tag className="mr-0">
              {kb.ingroup_permission === "EDIT"
                ? t("aidpKnowledge.scopeGroupEdit")
                : t("aidpKnowledge.scopeGroupRead")}
            </Tag>
          </>
        ) : type ? (
          <Tag className="mr-0">
            {t(
              type === "personal"
                ? "aidpKnowledge.kbTypePersonal"
                : "aidpKnowledge.kbTypeEnterprise"
            )}
          </Tag>
        ) : (
          <Tag className="mr-0">{AIDP_UNKNOWN_VALUE}</Tag>
        )}
        <Can permission="group:read">
          {groupNames.length > 0 && (
            <Tooltip title={groupNames.join("、")}>
              <Tag className="mr-0 max-w-36 truncate">
                {t("aidpKnowledge.scopeGroupCount", {
                  count: groupNames.length,
                })}
              </Tag>
            </Tooltip>
          )}
        </Can>
        {kb.permission === "READ_ONLY" && !isRowUnavailable(kb) && (
          <Tag color="default" className="mr-0">
            {t("aidpKnowledge.kbReadOnly")}
          </Tag>
        )}
        {isRowUnavailable(kb) && (
          <Tag color="default" className="mr-0">
            {t("aidpKnowledge.kbUnavailable")}
          </Tag>
        )}
      </div>
    );
  };

  const menuFor = (kb: AidpKnowledgeBaseItem): MenuProps => ({
    items: [
      {
        key: "import",
        icon: <FileAddOutlined />,
        label: t("aidpKnowledge.importFile"),
      },
      {
        type: "divider" as const,
      },
      {
        key: "delete",
        danger: true,
        icon: <Trash2 className="h-3.5 w-3.5" />,
        label: t("common.delete"),
      },
    ],
    onClick: ({ key, domEvent }) => {
      domEvent.stopPropagation();
      if (key === "import") onImport(kb);
      if (key === "delete") onDelete(kb);
    },
  });

  const renderMoreMenu = (kb: AidpKnowledgeBaseItem) =>
    canModify(kb) ? (
      <Dropdown menu={menuFor(kb)} trigger={["click"]}>
        <Button
          type="text"
          size="small"
          className={styles.cardMore}
          aria-label={t("aidpKnowledge.moreOperations")}
          icon={<EllipsisOutlined />}
          onClick={(event) => event.stopPropagation()}
        />
      </Dropdown>
    ) : null;

  const renderCards = () => (
    <div className={styles.cardGrid}>
      {displayedKbs.map((kb) => (
        <article
          key={kb.kds_id}
          role="button"
          tabIndex={0}
          onClick={() => onSelect(kb)}
          onKeyDown={(event) => {
            if (event.target !== event.currentTarget) return;
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              onSelect(kb);
            }
          }}
          className={styles.card}
        >
          <div className={styles.cardContent}>
            <div className={styles.cardHeader}>
              <span className={styles.cardIcon} aria-hidden="true">
                <DatabaseOutlined />
              </span>
              <h3 className={styles.cardTitle} title={kb.kds_name}>
                {kb.kds_name}
              </h3>
              {renderMoreMenu(kb)}
            </div>

            <p
              className={styles.cardDescription}
              title={kb.description || undefined}
            >
              {kb.description?.trim() || t("aidpKnowledge.noDescription")}
            </p>
          </div>

          <div className={styles.cardMetadata}>
            <span
              className={styles.cardDate}
              title={`${t("aidpKnowledge.cardUpdated")} ${formatAidpDateTime(kb.updated_at)}`}
            >
              <ClockCircleOutlined aria-hidden="true" />
              <span className={styles.metadataValue}>
                {t("aidpKnowledge.cardUpdated")} {formatCardDate(kb.updated_at)}
              </span>
            </span>
            <span
              className={styles.cardStatistic}
              title={t("aidpKnowledge.cardDocuments", {
                count: formatAidpDocumentCount(
                  kb.document_count,
                  kb.document_count_reliable
                ),
              })}
            >
              <FileTextOutlined aria-hidden="true" />
              <span className={styles.metadataValue}>
                {formatAidpDocumentCount(
                  kb.document_count,
                  kb.document_count_reliable
                )}
              </span>
            </span>
            <span
              className={styles.cardStatistic}
              title={t("aidpKnowledge.cardCapacity", {
                value: formatAidpCapacity(kb.current_cap),
              })}
            >
              <DatabaseOutlined aria-hidden="true" />
              <span className={styles.metadataValue}>
                {formatAidpCapacity(kb.current_cap)}
              </span>
            </span>
          </div>
        </article>
      ))}
    </div>
  );

  const handleResize = (key: AidpKbColumnKey, width: number) => {
    setColumnWidths((current) => ({ ...current, [key]: width }));
  };

  const renderTable = () => {
    const baseWidths: Record<AidpKbColumnKey, number> = {
      name: 220,
      type: 210,
      description: 280,
      documents: 100,
      capacity: 120,
      creator: 140,
      created_at: 140,
      actions: 220,
    };
    const makeColumn = (
      key: AidpKbColumnKey,
      column: ColumnsType<AidpKnowledgeBaseItem>[number]
    ) => ({
      ...column,
      width: columnWidths[key] ?? baseWidths[key],
      onHeaderCell: () =>
        ({
          width: columnWidths[key] ?? baseWidths[key],
          onResize: (width: number) => handleResize(key, width),
        }) as ResizableTitleProps,
    });
    const allColumns: Record<
      AidpKbColumnKey,
      ColumnsType<AidpKnowledgeBaseItem>[number]
    > = {
      name: makeColumn("name", {
        title: t("aidpKnowledge.columnName"),
        dataIndex: "kds_name",
        key: "name",
        fixed: "left",
        render: (_value, kb) => (
          <button
            type="button"
            className={`${styles.tableName} max-w-full truncate text-left font-medium`}
            title={kb.kds_name}
            onClick={(event) => {
              event.stopPropagation();
              onSelect(kb);
            }}
          >
            {kb.kds_name}
          </button>
        ),
      }),
      type: makeColumn("type", {
        title: t("aidpKnowledge.columnType"),
        key: "type",
        render: (_value, kb) => renderScope(kb),
      }),
      description: makeColumn("description", {
        title: t("aidpKnowledge.columnDescription"),
        dataIndex: "description",
        key: "description",
        ellipsis: true,
        render: (value: string | undefined) =>
          value?.trim() || AIDP_UNKNOWN_VALUE,
      }),
      documents: makeColumn("documents", {
        title: t("aidpKnowledge.columnDocuments"),
        key: "documents",
        render: (_value, kb) =>
          formatAidpDocumentCount(
            kb.document_count,
            kb.document_count_reliable
          ),
      }),
      capacity: makeColumn("capacity", {
        title: t("aidpKnowledge.columnCapacity"),
        key: "capacity",
        render: (_value, kb) => formatAidpCapacity(kb.current_cap),
      }),
      creator: makeColumn("creator", {
        title: t("aidpKnowledge.columnCreator"),
        key: "creator",
        render: (_value, kb) => formatAidpCreator(kb.user_name),
      }),
      created_at: makeColumn("created_at", {
        title: t("aidpKnowledge.columnCreatedAt"),
        key: "created_at",
        render: (_value, kb) => formatAidpDateTime(kb.created_at),
      }),
      actions: makeColumn("actions", {
        title: t("aidpKnowledge.columnActions"),
        key: "actions",
        fixed: "right",
        align: "right",
        render: (_value, kb) =>
          canModify(kb) ? (
            <div className="flex items-center justify-end gap-1 whitespace-nowrap">
              <Button
                type="link"
                size="small"
                className="px-1"
                onClick={(event) => {
                  event.stopPropagation();
                  onImport(kb);
                }}
              >
                {t("aidpKnowledge.importFile")}
              </Button>
              <Button
                type="link"
                danger
                size="small"
                className="px-1"
                onClick={(event) => {
                  event.stopPropagation();
                  onDelete(kb);
                }}
              >
                {t("common.delete")}
              </Button>
            </div>
          ) : null,
      }),
    };
    const activeKeys = AIDP_KB_DEFAULT_COLUMNS.filter(
      (key) =>
        AIDP_KB_REQUIRED_COLUMNS.includes(key) || visibleColumns.includes(key)
    );
    const totalWidth = activeKeys.reduce(
      (sum, key) => sum + (columnWidths[key] ?? baseWidths[key]),
      0
    );

    return (
      <Table<AidpKnowledgeBaseItem>
        rowKey="kds_id"
        size="middle"
        className="aidp-knowledge-table"
        columns={activeKeys.map((key) => allColumns[key])}
        dataSource={displayedKbs}
        pagination={false}
        components={{
          header: { cell: ResizableTitle },
        }}
        scroll={{ x: totalWidth }}
        onRow={(kb) => ({
          onClick: () => onSelect(kb),
          style: { cursor: "pointer" },
        })}
      />
    );
  };

  const renderEmptyState = () => (
    <div className="flex min-h-52 items-center justify-center p-8 text-center text-sm text-gray-500">
      {keyword.trim()
        ? t("aidpKnowledge.searchEmpty")
        : t("aidpKnowledge.listEmpty")}
    </div>
  );
  const renderFailedState = () => (
    <div className="flex min-h-52 flex-col items-center justify-center p-8 text-center">
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
        <div className="flex min-h-52 items-center justify-center p-8 text-sm text-gray-400">
          {t("aidpKnowledge.listLoading")}
        </div>
      );
    }
    if (loadFailed && displayedKbs.length === 0) return renderFailedState();
    if (displayedKbs.length === 0) return renderEmptyState();
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
    <ConfigProvider theme={aidpKnowledgeVisualTheme}>
      <div
        className={`${styles.overview} flex h-full min-h-0 w-full flex-col gap-3`}
      >
        <AidpKnowledgeGuide />
        <section className="flex min-h-0 flex-1 flex-col overflow-hidden bg-white">
          <div className={styles.toolbar}>
            <div className={styles.searchGroup}>
              <Input
                allowClear
                className={styles.searchInput}
                placeholder={t("aidpKnowledge.searchPlaceholder")}
                prefix={<SearchOutlined />}
                value={keyword}
                onChange={(event) => onKeywordChange(event.target.value)}
                size="middle"
              />
              <Tooltip title={t("aidpKnowledge.refresh")}>
                <Button
                  type="text"
                  aria-label={t("aidpKnowledge.refresh")}
                  icon={<ReloadOutlined spin={isLoading} />}
                  onClick={onRefresh}
                />
              </Tooltip>
            </div>
            <div className="ml-auto flex items-center justify-end gap-2">
              <Button
                type="primary"
                className={styles.createButton}
                onClick={onCreateNew}
              >
                {t("aidpKnowledge.createKb")}
              </Button>
              <Segmented
                className={styles.viewSwitch}
                value={viewMode}
                onChange={(value) => onViewModeChange(value as AidpKbViewMode)}
                options={[
                  {
                    value: "table",
                    title: t("aidpKnowledge.viewTable"),
                    label: <TableOutlined />,
                  },
                  {
                    value: "cards",
                    title: t("aidpKnowledge.viewCards"),
                    label: <AppstoreOutlined />,
                  },
                ]}
              />
              {viewMode === "table" && (
                <Popover
                  trigger="click"
                  placement="bottomRight"
                  content={columnSettingContent}
                >
                  <Tooltip title={t("aidpKnowledge.columnSettings")}>
                    <Button
                      aria-label={t("aidpKnowledge.columnSettings")}
                      icon={<SettingOutlined />}
                    />
                  </Tooltip>
                </Popover>
              )}
            </div>
          </div>
          <div className="min-h-0 flex-1 overflow-auto">{renderBody()}</div>
          {kbs.length > 0 && (
            <div className="flex shrink-0 pt-3">
              <AidpPagination
                currentPage={currentPage}
                pageSize={pageSize}
                total={total}
                totalReliable={totalReliable}
                hasMore={hasMore}
                onPageChange={onPageChange}
                onPageSizeChange={onPageSizeChange}
              />
            </div>
          )}
        </section>
      </div>
    </ConfigProvider>
  );
};

export default AidpKnowledgeList;
