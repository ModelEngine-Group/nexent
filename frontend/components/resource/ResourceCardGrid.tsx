// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { Table } from "antd";

import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  App,
  Button,
  Checkbox,
  Empty,
  Input,
  Pagination,
  Tag,
} from "antd";
import type { TableColumnType } from "antd";
import { useTranslation } from "react-i18next";
import { AgentCardTags } from "@/components/repository/agent/components/AgentCardTags";
import { getAgentRepositoryTagLabel } from "@/lib/agentRepositoryLabels";
import { useRepositoryPresentation } from "@/hooks/useRepositoryPresentation";
import { useUserDisplayName } from "@/hooks/auth/useUserDisplayName";
import { Search } from "lucide-react";
import type { CSSProperties, ReactNode } from "react";

import CreateResourceCard from "./CreateResourceCard";

export interface ResourceFilterOption {
  key: string;
  label: ReactNode;
  count?: number;
}

interface ResourceBatchState {
  selectedCount: number;
  deleting: boolean;
  selectPageControl: ReactNode;
  clearSelection: () => void;
  deleteSelected: () => void;
}

export interface ResourceCardGridProps<T> {
  items: T[];
  page?: number;
  total?: number;
  onPageChange?: (page: number) => void;
  onPageSizeChange?: (pageSize: number) => void;
  search?: string;
  searchPlaceholder?: string;
  onSearchChange?: (value: string) => void;
  filters?: ResourceFilterOption[];
  activeFilter?: string;
  onFilterChange?: (key: string) => void;
  showToolbar?: boolean;
  showCreateCard?: boolean;
  createCard?: ReactNode;
  createCardTitle?: string;
  onCreate?: () => void;
  /** Defaults to responsive columns matching the agent configuration list. */
  columns?: number;
  /** Override paging independently of the visual column and row counts. */
  pageSize?: number;
  rows?: number;
  /** Constrain the card grid to this height and distribute cards across rows. */
  gridHeight?: number;
  /** Keep support for callers that need to place another item before the cards. */
  headerItem?: ReactNode;
  emptyState?: ReactNode;
  /** Set to false when items already contain only the current server page. */
  paginateItems?: boolean;
  renderItem: (item: T, index: number, selection?: ReactNode) => ReactNode;
  renderBatchToolbar?: (
    controls: ReactNode,
    state: ResourceBatchState
  ) => ReactNode;
  cardSelectionInHeader?: boolean;
  onListSelect?: (item: T) => void;
  renderListStatus?: (item: T) => ReactNode;
  renderListActions?: (item: T) => ReactNode;
  batchDelete?: (item: T) => Promise<void>;
  batchDeleteItems?: (items: T[]) => Promise<Map<string, string>>;
  canBatchDelete?: (item: T) => boolean;
  getItemKey?: (item: T) => string;
  selectionKey?: string;
  isCreateItem?: (item: T) => boolean;
}

export default function ResourceCardGrid<T>({
  items,
  page,
  total,
  onPageChange,
  onPageSizeChange,
  search,
  searchPlaceholder,
  onSearchChange,
  filters = [],
  activeFilter,
  onFilterChange,
  showToolbar,
  showCreateCard,
  createCard,
  createCardTitle,
  onCreate,
  columns,
  pageSize,
  rows,
  gridHeight,
  headerItem,
  emptyState = <Empty />,
  paginateItems = true,
  renderItem,
  renderBatchToolbar,
  cardSelectionInHeader,
  onListSelect,
  renderListStatus,
  renderListActions,
  batchDelete,
  batchDeleteItems,
  canBatchDelete,
  getItemKey,
  selectionKey,
  isCreateItem,
}: ResourceCardGridProps<T>) {
  const presentation = useRepositoryPresentation();
  const isAgentRepository =
    presentation?.resourceType === "agent" &&
    presentation.query?.get("view") !== "mine";
  const isMcpRepository =
    presentation?.resourceType === "mcp" &&
    presentation.query?.get("view") !== "mine";
  const isMineMcp =
    presentation?.resourceType === "mcp" &&
    presentation.query?.get("view") === "mine";
  const useRepositoryCardLayout = isAgentRepository || isMcpRepository;
  const useResponsiveCards =
    useRepositoryCardLayout || presentation?.resourceType === "mcp";
  const { t } = useTranslation("common");
  const displayName = useUserDisplayName();
  const authorColumn: TableColumnType<T & object> = {
    title: t("resourceCenter.author"),
    render: (_, item) => {
      const row = resourceValues(item);
      return displayName(
        String(row.author_cas_username || row.authorCasUsername || ""),
        String(row.author || row.authorDisplayName || row.submitted_by || "—")
      );
    },
  };
  const { modal } = App.useApp();
  const [selected, setSelected] = useState<string[]>([]);
  const [batchErrors, setBatchErrors] = useState<string[]>([]);
  const [deleting, setDeleting] = useState(false);
  const keyOf = (item: T) => {
    if (getItemKey) return getItemKey(item);
    const row = item as unknown as Record<string, unknown>;
    return String(
      row.agent_repository_id ??
        row.skill_repository_id ??
        row.communityId ??
        row.skill_id ??
        row.agent_id ??
        row.name
    );
  };
  const batching =
    !!presentation && !!(batchDeleteItems || batchDelete) && !!canBatchDelete;
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- Selection is scoped to a page and filter context.
    setSelected([]);
    setBatchErrors([]);
  }, [batching, page, selectionKey]);

  const columnCount = normalizePositiveInteger(columns, 4);
  const rowCount = normalizePositiveInteger(rows, 3);
  const slotsPerPage = normalizePositiveInteger(
    pageSize,
    columnCount * rowCount
  );
  const createEnabled =
    showCreateCard ?? Boolean(createCard || (createCardTitle && onCreate));
  const itemsPerPage =
    createEnabled && !presentation
      ? Math.max(1, slotsPerPage - 1)
      : slotsPerPage;
  const itemCount = total ?? items.length;
  const totalPages = Math.max(1, Math.ceil(itemCount / itemsPerPage));
  const currentPage = Math.min(Math.max(page ?? 1, 1), totalPages);
  const visibleItems = useMemo(() => {
    if (!paginateItems) return items;
    const start = (currentPage - 1) * itemsPerPage;
    return items.slice(start, start + itemsPerPage);
  }, [currentPage, items, itemsPerPage, paginateItems]);
  const selectable = batching
    ? visibleItems.filter((item) => canBatchDelete!(item))
    : [];
  const removeSelected = () =>
    modal.confirm({
      title: t("resourceCenter.deleteSelected"),
      content: t("resourceCenter.selectedCount", { count: selected.length }),
      centered: true,
      okButtonProps: { danger: true },
      okText: t("common.confirm"),
      cancelText: t("common.cancel"),
      onOk: async () => {
        setDeleting(true);
        const failed: string[] = [];
        const errors: string[] = [];
        const targets = selectable.filter((item) =>
          selected.includes(keyOf(item))
        );
        if (batchDeleteItems && targets.length) {
          try {
            const failures = await batchDeleteItems(targets);
            failed.push(...failures.keys());
            errors.push(...failures.values());
          } catch (error) {
            failed.push(...targets.map(keyOf));
            errors.push(
              error instanceof Error
                ? error.message
                : t("resourceCenter.operationFailed")
            );
          }
        } else if (batchDelete) {
          for (const item of targets) {
            try {
              await batchDelete(item);
            } catch (error) {
              failed.push(keyOf(item));
              errors.push(
                error instanceof Error
                  ? error.message
                  : t("resourceCenter.operationFailed")
              );
            }
          }
        }
        setSelected(failed);
        setBatchErrors(errors);
        setDeleting(false);
      },
    });
  const shouldShowCreateCard = createEnabled;
  const createCardNode = shouldShowCreateCard
    ? (createCard ??
      (createCardTitle && onCreate ? (
        <CreateResourceCard title={createCardTitle} onClick={onCreate} />
      ) : null))
    : null;
  const toolbarVisible =
    showToolbar ??
    Boolean(onSearchChange || search !== undefined || filters.length > 0);
  const hasSearchControl = onSearchChange !== undefined || search !== undefined;
  const gridStyle = {
    "--resource-card-columns": columnCount,
    "--resource-card-rows": rowCount,
    ...(gridHeight !== undefined ? { height: `${gridHeight}px` } : {}),
  } as CSSProperties;

  useEffect(() => {
    if (page !== undefined && page > totalPages) onPageChange?.(totalPages);
  }, [onPageChange, page, totalPages]);

  const selectPageControl = (
    <Checkbox
      disabled={deleting || !selectable.length}
      checked={
        selectable.length > 0 &&
        selectable.every((item) => selected.includes(keyOf(item)))
      }
      indeterminate={selected.length > 0 && selected.length < selectable.length}
      onChange={(event) =>
        setSelected(event.target.checked ? selectable.map(keyOf) : [])
      }
    >
      {t("resourceCenter.selectPage")}
    </Checkbox>
  );
  const batchControls = batching ? (
    <div className="flex shrink-0 items-center gap-3">
      {selectPageControl}
      <Button
        danger
        disabled={!selected.length}
        loading={deleting}
        onClick={removeSelected}
      >
        {t("resourceCenter.deleteSelected")} ({selected.length})
      </Button>
    </div>
  ) : null;

  return (
    <>
      {renderBatchToolbar
        ? renderBatchToolbar(batchControls, {
            selectedCount: selected.length,
            deleting,
            selectPageControl,
            clearSelection: () => setSelected([]),
            deleteSelected: () => {
              if (selected.length && !deleting) removeSelected();
            },
          })
        : batchControls && <div className="mb-3">{batchControls}</div>}
      {batchErrors.length > 0 && (
        <Alert
          type="error"
          showIcon
          className="mb-3"
          message={t("resourceCenter.partialFailure", {
            count: batchErrors.length,
          })}
          description={batchErrors.join("; ")}
        />
      )}
      {toolbarVisible ? (
        <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          {hasSearchControl ? (
            <Input
              value={search ?? ""}
              onChange={(event) => onSearchChange?.(event.target.value)}
              allowClear={onSearchChange !== undefined}
              readOnly={onSearchChange === undefined}
              prefix={<Search size={16} className="text-slate-400" />}
              placeholder={searchPlaceholder}
              className="h-10 w-full sm:max-w-md"
            />
          ) : null}
          {filters.length > 0 ? (
            <div className="flex items-center gap-5 border-b border-slate-200 text-sm">
              {filters.map((filter) => (
                <button
                  key={filter.key}
                  type="button"
                  aria-pressed={activeFilter === filter.key}
                  onClick={() => onFilterChange?.(filter.key)}
                  className={cnFilter(activeFilter === filter.key)}
                >
                  {filter.label}
                  {filter.count !== undefined ? (
                    <span className="ml-1 text-xs text-slate-400">
                      {filter.count}
                    </span>
                  ) : null}
                </button>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
      {presentation?.layout === "list" &&
        (createCardNode ||
          visibleItems.some((item) => isCreateItem?.(item))) && (
          <div className="mb-3 flex justify-end gap-2">
            {createCardNode}
            {visibleItems
              .filter((item) => isCreateItem?.(item))
              .map((item, index) => renderItem(item, index))}
          </div>
        )}
      {presentation?.layout === "list" ? (
        <Table<T & object>
          className="resource-scroll-table w-full"
          scroll={{ x: 1200, y: "100%" }}
          tableLayout="fixed"
          size="middle"
          pagination={false}
          dataSource={
            visibleItems.filter((item) => !isCreateItem?.(item)) as (T &
              object)[]
          }
          rowSelection={
            batching
              ? {
                  selectedRowKeys: selected,
                  onChange: (keys) => setSelected(keys.map(String)),
                  getCheckboxProps: (item) => ({
                    disabled: deleting || !canBatchDelete!(item),
                  }),
                }
              : undefined
          }
          rowKey={keyOf}
          columns={[
            {
              title: t("resourceCenter.name"),
              width: isAgentRepository ? 312 : undefined,
              ellipsis: true,
              render: (_, item) => {
                const row = resourceValues(item);
                const name = String(
                  row.display_name || row.name || row.skill_name || "—"
                );
                return onListSelect ? (
                  <Button
                    type="link"
                    className="!h-auto max-w-full !px-0 !py-0 !text-[#0067D1] [&>span]:truncate"
                    title={name}
                    onClick={() => onListSelect(item)}
                  >
                    {name}
                  </Button>
                ) : (
                  name
                );
              },
            },
            ...(isMineMcp && renderListStatus
              ? [
                  {
                    title: t("mcpTools.mine.statusColumn"),
                    width: 184,
                    render: (_: unknown, item: T & object) =>
                      renderListStatus(item),
                  },
                ]
              : []),
            {
              title: t("resourceCenter.tags"),
              width: useRepositoryCardLayout || isMineMcp ? 156 : undefined,
              render: (_, item) => {
                const tags = resourceValues(item).tags;
                if (
                  (useRepositoryCardLayout || isMineMcp) &&
                  Array.isArray(tags)
                ) {
                  return (
                    <AgentCardTags
                      labels={tags.map((tag) =>
                        isAgentRepository
                          ? getAgentRepositoryTagLabel(String(tag), t)
                          : String(tag)
                      )}
                    />
                  );
                }
                return Array.isArray(tags) ? (
                  <div className="flex gap-1 overflow-hidden">
                    {tags.map((tag) => (
                      <Tag key={String(tag)}>{String(tag)}</Tag>
                    ))}
                  </div>
                ) : (
                  "—"
                );
              },
            },
            ...(isAgentRepository
              ? [
                  {
                    title: t("resourceCenter.type"),
                    width: "6%",
                    render: (_: unknown, item: T & object) => {
                      const row = resourceValues(item);
                      if (row.is_official === true) {
                        return t("agentRepository.card.official");
                      }
                      return row.is_main_agent === false
                        ? t("space.detail.tabs.subAgents")
                        : t("agentRepository.card.mainAgent");
                    },
                  },
                ]
              : []),
            ...(presentation?.resourceType !== "mcp"
              ? [
                  {
                    title: t("resourceCenter.version"),
                    render: (_: unknown, item: T & object) => {
                      const row = resourceValues(item);
                      return String(
                        row.version_label ??
                          row.version_name ??
                          row.current_version_no ??
                          row.version_no ??
                          row.version ??
                          "—"
                      );
                    },
                  },
                ]
              : []),
            {
              title: t("resourceCenter.description"),
              ellipsis: true,
              render: (_, item) =>
                String(resourceValues(item).description || "—"),
            },
            ...(!isAgentRepository ? [authorColumn] : []),
            {
              title: t("resourceCenter.downloads"),
              render: (_, item) => {
                const row = resourceValues(item);
                return String(row.downloads ?? row.installCount ?? 0);
              },
            },
            ...(isAgentRepository ? [authorColumn] : []),
            {
              title: t("resourceCenter.publishedAt"),
              render: (_, item) => {
                const row = resourceValues(item);
                const value = row.published_at || row.publishedAt;
                return value
                  ? new Date(String(value)).toLocaleString()
                  : t("resourceCenter.notRecorded");
              },
            },
            ...(presentation
              ? [
                  {
                    title: t("resourceCenter.actions"),
                    width: isAgentRepository ? 167 : 160,
                    fixed: "right" as const,
                    render: (_: unknown, item: T & object) =>
                      renderListActions
                        ? renderListActions(item)
                        : renderItem(item, visibleItems.indexOf(item)),
                  },
                ]
              : []),
          ]}
        />
      ) : (
        <div
          className={
            useResponsiveCards
              ? "repository-card-body @container min-h-0 overflow-y-auto"
              : presentation
                ? "@container"
                : undefined
          }
        >
          <div
            className={`grid ${
              presentation
                ? useResponsiveCards
                  ? "gap-4"
                  : "gap-x-4 gap-y-3"
                : "gap-5"
            } ${
              columns === undefined
                ? presentation
                  ? presentation.resourceType === "skill"
                    ? "grid-cols-1 @min-[720px]:grid-cols-2 @min-[1200px]:grid-cols-3"
                    : useResponsiveCards
                      ? "grid-cols-[repeat(auto-fill,minmax(min(100%,max(440px,calc((100%_-_48px)/4))),1fr))]"
                      : "grid-cols-1 @min-[1200px]:grid-cols-[repeat(auto-fill,592px)]"
                  : "grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4"
                : "grid-cols-1 min-[576px]:grid-cols-2 lg:[grid-template-columns:repeat(var(--resource-card-columns),minmax(0,1fr))]"
            } ${
              gridHeight !== undefined
                ? "grid-rows-[repeat(var(--resource-card-rows),minmax(0,1fr))]"
                : ""
            }`}
            style={gridStyle}
          >
            {headerItem != null && currentPage === 1 ? headerItem : null}
            {createCardNode}
            {itemCount === 0 && !createCardNode ? (
              <div className="col-span-full flex min-h-[220px] items-center justify-center">
                {emptyState}
              </div>
            ) : (
              visibleItems.map((item, index) => {
                if (!batching) return renderItem(item, index);
                const selection = (
                  <Checkbox
                    className={
                      cardSelectionInHeader
                        ? undefined
                        : "absolute left-3 top-5 z-20"
                    }
                    aria-label={String(resourceValues(item).name ?? "")}
                    disabled={deleting || !canBatchDelete!(item)}
                    checked={selected.includes(keyOf(item))}
                    onChange={(event) =>
                      setSelected((current) =>
                        event.target.checked
                          ? [...current, keyOf(item)]
                          : current.filter((key) => key !== keyOf(item))
                      )
                    }
                  />
                );
                if (cardSelectionInHeader)
                  return renderItem(item, index, selection);
                return (
                  <div key={keyOf(item)} className="relative [&>.group]:pl-10">
                    {selection}
                    {renderItem(item, index)}
                  </div>
                );
              })
            )}
          </div>
        </div>
      )}

      {itemCount > 0 && onPageChange ? (
        <div
          className={
            presentation
              ? "resource-repository-pagination my-4 shrink-0"
              : "mt-7 flex justify-end"
          }
        >
          <Pagination
            current={currentPage}
            pageSize={itemsPerPage}
            total={itemCount}
            showTotal={
              presentation
                ? (count) => t("resourceCenter.total", { count })
                : undefined
            }
            showSizeChanger={Boolean(onPageSizeChange)}
            pageSizeOptions={[10, 12, 20, 50, 100]}
            showQuickJumper={Boolean(presentation) && itemCount > itemsPerPage}
            onChange={(nextPage, size) => {
              if (size !== itemsPerPage && onPageSizeChange)
                onPageSizeChange(size);
              else onPageChange(nextPage);
            }}
          />
        </div>
      ) : null}
    </>
  );
}

function normalizePositiveInteger(value: number | undefined, fallback: number) {
  return Number.isFinite(value) && value !== undefined && value > 0
    ? Math.floor(value)
    : fallback;
}

function cnFilter(active: boolean) {
  return `border-b-2 px-1 pb-2 font-medium transition-colors ${
    active
      ? "border-blue-600 text-blue-600"
      : "border-transparent text-slate-500 hover:text-slate-800"
  }`;
}

function resourceValues(item: unknown): Record<string, unknown> {
  const row = item as Record<string, unknown>;
  return row.service && typeof row.service === "object"
    ? (row.service as Record<string, unknown>)
    : row;
}
