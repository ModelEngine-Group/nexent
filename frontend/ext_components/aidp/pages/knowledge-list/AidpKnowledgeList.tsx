"use client";

import React, { useMemo } from "react";
import { useTranslation } from "react-i18next";

import {
  Alert,
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

import type { AidpKnowledgeBaseItem } from "@/ext_components/aidp/shared/types/knowledge";
import {
  AIDP_UNKNOWN_VALUE,
  formatAidpCreator,
  formatAidpDateTime,
} from "@/ext_components/aidp/shared/utils/aidpKnowledgeDisplay";
import { useAidpGroupOptions } from "@/ext_components/aidp/shared/hooks/useAidpGroupOptions";
import { usePermission } from "@/hooks/permission/usePermission";
import { getAidpErrorMessage } from "@/ext_components/aidp/shared/utils/aidpErrorUtils";
import { Can } from "@/components/permission/Can";
import { AIDP_MIN_COLUMN_WIDTH } from "@/ext_components/aidp/pages/knowledge-list/utils/aidpKnowledgeColumnWidths";
import AidpResizableTitle, {
  type AidpResizableTitleProps,
} from "@/ext_components/aidp/pages/knowledge-list/AidpResizableTitle";
import AidpKnowledgeGuide from "@/ext_components/aidp/pages/knowledge-list/AidpKnowledgeGuide";
import AidpPagination from "@/ext_components/aidp/shared/components/AidpPagination";
import { aidpKnowledgeVisualTheme } from "@/ext_components/aidp/shared/styles/aidpKnowledgeVisualTheme";
import styles from "./AidpKnowledgeList.module.css";
import { useAidpColumnWidths } from "./hooks/useAidpColumnWidths";
import type { AidpKbColumnKey, AidpKbViewMode } from "./types";
import {
  AIDP_KB_REQUIRED_COLUMNS,
  AIDP_KB_DEFAULT_COLUMNS,
  COLUMN_LABEL_KEYS,
} from "./constants";

/** Keep the compact card date in the UCD year-month-day format. */
function formatCardDate(value: unknown): string {
  if (formatAidpDateTime(value) === AIDP_UNKNOWN_VALUE)
    return AIDP_UNKNOWN_VALUE;
  return new Date(value as string).toLocaleDateString("sv-SE");
}

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
  const { can } = usePermission();
  const { groupOptions, groupsError } = useAidpGroupOptions();
  const groupById = useMemo(() => {
    const map = new Map<number, string>();
    groupOptions.forEach((group) => {
      map.set(group.value, group.label);
    });
    return map;
  }, [groupOptions]);
  const { tableContainer, activeKeys, columnWidths, handleResize } =
    useAidpColumnWidths(visibleColumns);

  const displayedKbs = kbs;

  const isRowUnavailable = (kb: AidpKnowledgeBaseItem) =>
    kb.resource_status === "UNAVAILABLE" || kb.resource_status === "ORPHANED";
  const canModify = (kb: AidpKnowledgeBaseItem) =>
    kb.permission === "EDIT" && !isRowUnavailable(kb);

  const getGroupNames = (ids: number[] | undefined) =>
    Array.isArray(ids)
      ? ids.map((id) => groupById.get(id) || AIDP_UNKNOWN_VALUE)
      : [];

  const scopeDescription = (kb: AidpKnowledgeBaseItem) => {
    const isPrivate = kb.ingroup_permission === "PRIVATE";
    const isShared =
      kb.ingroup_permission === "EDIT" || kb.ingroup_permission === "READ_ONLY";
    return {
      isPrivate,
      isShared,
      groupNames:
        isShared && can("group:read") && !groupsError
          ? getGroupNames(kb.group_ids)
          : [],
      scope: isPrivate
        ? t("aidpKnowledge.scopePrivate")
        : isShared
          ? t("aidpKnowledge.scopeShared")
          : AIDP_UNKNOWN_VALUE,
      groupPermission: isShared
        ? t(
            kb.ingroup_permission === "EDIT"
              ? "aidpKnowledge.scopeGroupEdit"
              : "aidpKnowledge.scopeGroupRead"
          )
        : "",
      readOnly: kb.permission === "READ_ONLY" && !isRowUnavailable(kb),
      unavailable: isRowUnavailable(kb),
    };
  };
  const scopeText = (kb: AidpKnowledgeBaseItem) => {
    const scope = scopeDescription(kb);
    return [
      scope.scope,
      scope.groupPermission,
      scope.groupNames.join("、"),
      scope.readOnly ? t("aidpKnowledge.kbReadOnly") : "",
      scope.unavailable ? t("aidpKnowledge.kbUnavailable") : "",
    ]
      .filter(Boolean)
      .join(" · ");
  };
  const renderScope = (kb: AidpKnowledgeBaseItem) => {
    const scope = scopeDescription(kb);
    return (
      <div className={styles.tableScope}>
        <Tag
          color={
            scope.isPrivate ? "blue" : scope.isShared ? "geekblue" : undefined
          }
          className="mr-0"
        >
          {scope.scope}
        </Tag>
        {scope.groupPermission && (
          <Tag className="mr-0">{scope.groupPermission}</Tag>
        )}
        {scope.groupNames.length > 0 && (
          <Tooltip title={scope.groupNames.join("、")}>
            <Tag className={`${styles.tableGroup} mr-0`}>
              {t("aidpKnowledge.scopeGroupCount", {
                count: scope.groupNames.length,
              })}
            </Tag>
          </Tooltip>
        )}
        {scope.readOnly && (
          <Tag color="default" className="mr-0">
            {t("aidpKnowledge.kbReadOnly")}
          </Tag>
        )}
        {scope.unavailable && (
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
      ...(can("kb:delete")
        ? [
            { type: "divider" as const },
            {
              key: "delete",
              icon: <Trash2 className="h-3.5 w-3.5" />,
              label: t("common.delete"),
            },
          ]
        : []),
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

  const renderTable = () => {
    const renderText = (value: string | number) => (
      <Tooltip title={value}>
        <span className={styles.tableCellText}>{value}</span>
      </Tooltip>
    );
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
                <Can permission="kb:delete">
                  <Button
                    type="link"
                    size="small"
                    className="px-1"
                    onClick={(event) => {
                      event.stopPropagation();
                      onDelete(kb);
                    }}
                  >
                    {t("common.delete")}
                  </Button>
                </Can>
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
          {loadFailed && displayedKbs.length > 0 && (
            <Alert
              type="error"
              showIcon
              title={loadError || t("aidpKnowledge.listLoadFailed")}
              className="mb-3 shrink-0"
            />
          )}
          {groupsError && (
            <Alert
              type="error"
              showIcon
              className="mb-3 shrink-0"
              title={getAidpErrorMessage(
                groupsError,
                t,
                t("aidpKnowledge.groupsLoadFailed")
              )}
            />
          )}
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
                  className={styles.searchRefresh}
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
          {(total > 0 || currentPage > 1) && (
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
