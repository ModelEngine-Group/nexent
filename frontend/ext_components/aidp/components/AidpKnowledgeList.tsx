"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
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
  ReloadOutlined,
  SearchOutlined,
  SettingOutlined,
  TableOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { Trash2 } from "lucide-react";

import type { AidpKnowledgeBaseItem } from "@/types/agentConfig";
import {
  AIDP_UNKNOWN_VALUE,
  formatAidpCreator,
  formatAidpDateTime,
  normalizeAidpKbType,
} from "@/lib/aidpKnowledgeDisplay";
import { useGroupList } from "@/hooks/group/useGroupList";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { Can } from "@/components/permission/Can";
import {
  AIDP_MIN_COLUMN_WIDTH,
  fitAidpColumnWidths,
  resizeAidpColumnPair,
} from "@/lib/aidpKnowledgeColumnWidths";
import AidpResizableTitle, {
  type AidpResizableTitleProps,
} from "./AidpResizableTitle";
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
  "name" | "type" | "description" | "creator" | "created_at" | "actions";

/** Columns the user cannot hide: the entry point and the row actions. */
export const AIDP_KB_REQUIRED_COLUMNS: AidpKbColumnKey[] = ["name", "actions"];

/** Default visible column set, used on first render and by "restore". */
export const AIDP_KB_DEFAULT_COLUMNS: AidpKbColumnKey[] = [
  "name",
  "type",
  "description",
  "creator",
  "created_at",
  "actions",
];

const COLUMN_LABEL_KEYS: Record<AidpKbColumnKey, string> = {
  name: "aidpKnowledge.columnName",
  type: "aidpKnowledge.columnType",
  description: "aidpKnowledge.columnDescription",
  creator: "aidpKnowledge.columnCreator",
  created_at: "aidpKnowledge.columnCreatedAt",
  actions: "aidpKnowledge.columnActions",
};

interface AidpKnowledgeListProps {
  kbs: AidpKnowledgeBaseItem[];
  isLoading: boolean;
  loadFailed: boolean;
  loadError?: string;
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

const BASE_COLUMN_WEIGHTS: Record<AidpKbColumnKey, number> = {
  name: 280,
  type: 260,
  description: 418,
  creator: 180,
  created_at: 160,
  actions: 144,
};

const AidpKnowledgeList: React.FC<AidpKnowledgeListProps> = ({
  kbs,
  isLoading,
  loadFailed,
  loadError,
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
  const [columnWeights, setColumnWeights] = useState(BASE_COLUMN_WEIGHTS);
  const tableContainer = useRef<HTMLElement>(null);
  const [containerWidth, setContainerWidth] = useState(0);
  useEffect(() => {
    const element = tableContainer.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => {
      setContainerWidth(entry.contentRect.width);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const activeKeys = AIDP_KB_DEFAULT_COLUMNS.filter(
    (key) =>
      AIDP_KB_REQUIRED_COLUMNS.includes(key) || visibleColumns.includes(key)
  );
  const columnWidths = fitAidpColumnWidths(
    activeKeys,
    columnWeights,
    containerWidth ||
      activeKeys.reduce((sum, key) => sum + columnWeights[key], 0)
  );

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
      <div className={styles.tableScope}>
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
              <Tag className={`${styles.tableGroup} mr-0`}>
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
              title={`${t("aidpKnowledge.cardCreated")} ${formatAidpDateTime(kb.created_at)}`}
            >
              <ClockCircleOutlined aria-hidden="true" />
              <span className={styles.metadataValue}>
                {t("aidpKnowledge.cardCreated")} {formatCardDate(kb.created_at)}
              </span>
            </span>
            <span
              className={styles.cardStatistic}
              title={t("aidpKnowledge.columnCreator")}
            >
              <UserOutlined aria-hidden="true" />
              <span className={styles.metadataValue}>
                {formatAidpCreator(kb.creator_name)}
              </span>
            </span>
          </div>
        </article>
      ))}
    </div>
  );

  const handleResize = (
    key: AidpKbColumnKey,
    nextKey: AidpKbColumnKey,
    delta: number,
    renderedWidths: Record<string, number>
  ) => {
    const resized = resizeAidpColumnPair(renderedWidths, key, nextKey, delta);
    if (
      Math.abs(resized[key] - columnWidths[key]) < 0.02 &&
      Math.abs(resized[nextKey] - columnWidths[nextKey]) < 0.02
    )
      return;
    // Preserve hidden-column preferences in the same weight scale.
    setColumnWeights((current) => {
      const totalWeight = activeKeys.reduce(
        (sum, item) => sum + current[item],
        0
      );
      const totalWidth = activeKeys.reduce(
        (sum, item) => sum + resized[item],
        0
      );
      const next = { ...current };
      activeKeys.forEach((item) => {
        next[item] = (resized[item] / totalWidth) * totalWeight;
      });
      return next;
    });
  };

  const renderTable = () => {
    const renderText = (value: string | number) => (
      <Tooltip title={value}>
        <span className={styles.tableCellText}>{value}</span>
      </Tooltip>
    );
    const scopeText = (kb: AidpKnowledgeBaseItem) => {
      const shared =
        kb.ingroup_permission === "EDIT" ||
        kb.ingroup_permission === "READ_ONLY";
      const type = normalizeAidpKbType(kb.is_private);
      return (
        <>
          {kb.ingroup_permission === "PRIVATE"
            ? t("aidpKnowledge.scopePrivate")
            : shared
              ? `${t("aidpKnowledge.scopeShared")} · ${t(kb.ingroup_permission === "EDIT" ? "aidpKnowledge.scopeGroupEdit" : "aidpKnowledge.scopeGroupRead")}`
              : type
                ? t(
                    type === "personal"
                      ? "aidpKnowledge.kbTypePersonal"
                      : "aidpKnowledge.kbTypeEnterprise"
                  )
                : AIDP_UNKNOWN_VALUE}
          <Can permission="group:read">
            {shared && getGroupNames(kb.group_ids).length > 0
              ? ` · ${getGroupNames(kb.group_ids).join("、")}`
              : null}
          </Can>
          {kb.permission === "READ_ONLY" && !isRowUnavailable(kb)
            ? ` · ${t("aidpKnowledge.kbReadOnly")}`
            : null}
          {isRowUnavailable(kb)
            ? ` · ${t("aidpKnowledge.kbUnavailable")}`
            : null}
        </>
      );
    };
    const makeColumn = (
      key: AidpKbColumnKey,
      column: ColumnsType<AidpKnowledgeBaseItem>[number]
    ) => {
      const nextKey = activeKeys[activeKeys.indexOf(key) + 1];
      return {
        ...column,
        title: renderText(t(COLUMN_LABEL_KEYS[key])),
        ellipsis: { showTitle: false },
        width: columnWidths[key],
        onHeaderCell: () =>
          ({
            width: columnWidths[key],
            maxWidth: nextKey
              ? columnWidths[key] +
                columnWidths[nextKey] -
                AIDP_MIN_COLUMN_WIDTH
              : undefined,
            "data-column-key": key,
            onResize: nextKey
              ? (delta: number, renderedWidths: Record<string, number>) =>
                  handleResize(key, nextKey, delta, renderedWidths)
              : undefined,
          }) as AidpResizableTitleProps,
      };
    };
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
          <Tooltip title={kb.kds_name}>
            <button
              type="button"
              className={`${styles.tableName} max-w-full truncate text-left`}
              onClick={(event) => {
                event.stopPropagation();
                onSelect(kb);
              }}
            >
              {kb.kds_name}
            </button>
          </Tooltip>
        ),
      }),
      type: makeColumn("type", {
        title: t("aidpKnowledge.columnType"),
        key: "type",
        render: (_value, kb) => (
          <Tooltip title={scopeText(kb)}>
            {columnWidths.type >= 260 ? (
              <div>{renderScope(kb)}</div>
            ) : (
              <span className={styles.tableCellText}>{scopeText(kb)}</span>
            )}
          </Tooltip>
        ),
      }),
      description: makeColumn("description", {
        title: t("aidpKnowledge.columnDescription"),
        dataIndex: "description",
        key: "description",
        ellipsis: true,
        render: (value: string | undefined) =>
          renderText(value?.trim() || AIDP_UNKNOWN_VALUE),
      }),
      creator: makeColumn("creator", {
        title: t("aidpKnowledge.columnCreator"),
        key: "creator",
        render: (_value, kb) => renderText(formatAidpCreator(kb.creator_name)),
      }),
      created_at: makeColumn("created_at", {
        title: t("aidpKnowledge.columnCreatedAt"),
        key: "created_at",
        render: (_value, kb) => renderText(formatAidpDateTime(kb.created_at)),
      }),
      actions: makeColumn("actions", {
        title: t("aidpKnowledge.columnActions"),
        key: "actions",
        fixed: "right",
        align: "left",
        render: (_value, kb) =>
          canModify(kb) ? (
            columnWidths.actions < 144 ? (
              renderMoreMenu(kb)
            ) : (
              <div className={styles.tableActions}>
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
            )
          ) : null,
      }),
    };
    const totalWidth = activeKeys.reduce(
      (sum, key) => sum + columnWidths[key],
      0
    );

    return (
      <div
        className={styles.tableArea}
        style={
          { "--aidp-table-width": `${totalWidth}px` } as React.CSSProperties
        }
      >
        <Table<AidpKnowledgeBaseItem>
          rowKey="kds_id"
          size="middle"
          className={styles.knowledgeTable}
          columns={activeKeys.map((key) => allColumns[key])}
          dataSource={displayedKbs}
          pagination={false}
          tableLayout="fixed"
          components={{
            header: { cell: AidpResizableTitle },
          }}
          scroll={{ x: totalWidth }}
          onRow={(kb) => ({
            onClick: () => onSelect(kb),
            style: { cursor: "pointer" },
          })}
        />
      </div>
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
        {loadError || t("aidpKnowledge.listLoadFailed")}
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
        <section
          ref={tableContainer}
          className="flex min-h-0 flex-1 flex-col overflow-hidden bg-white"
        >
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
