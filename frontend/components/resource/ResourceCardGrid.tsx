"use client";

import { useEffect, useMemo } from "react";
import { Empty, Input, Pagination } from "antd";
import { Search } from "lucide-react";
import type { CSSProperties, ReactNode } from "react";

import CreateResourceCard from "./CreateResourceCard";

export interface ResourceFilterOption {
  key: string;
  label: ReactNode;
  count?: number;
}

export interface ResourceCardGridProps<T> {
  items: T[];
  page?: number;
  total?: number;
  onPageChange?: (page: number) => void;
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
  columns?: number;
  rows?: number;
  /** Keep support for callers that need to place another item before the cards. */
  headerItem?: ReactNode;
  emptyState?: ReactNode;
  /** Set to false when items already contain only the current server page. */
  paginateItems?: boolean;
  renderItem: (item: T, index: number) => ReactNode;
}

export default function ResourceCardGrid<T>({
  items,
  page,
  total,
  onPageChange,
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
  rows,
  headerItem,
  emptyState = <Empty />,
  paginateItems = true,
  renderItem,
}: ResourceCardGridProps<T>) {
  const columnCount = normalizePositiveInteger(columns, 4);
  const rowCount = normalizePositiveInteger(rows, 3);
  const slotsPerPage = columnCount * rowCount;
  const createEnabled =
    showCreateCard ?? Boolean(createCard || (createCardTitle && onCreate));
  const itemsPerPage = createEnabled
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
  } as CSSProperties;

  useEffect(() => {
    if (page !== undefined && page > totalPages) onPageChange?.(totalPages);
  }, [onPageChange, page, totalPages]);

  return (
    <>
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
      <div
        className="grid grid-cols-1 gap-5 sm:[grid-template-columns:repeat(var(--resource-card-columns),minmax(0,1fr))]"
        style={gridStyle}
      >
        {headerItem != null && currentPage === 1 ? headerItem : null}
        {createCardNode}
        {items.length === 0 ? (
          <div className="col-span-full flex min-h-[220px] items-center justify-center">
            {emptyState}
          </div>
        ) : (
          visibleItems.map((item, index) => renderItem(item, index))
        )}
      </div>
      {itemCount > 0 && totalPages > 1 && onPageChange ? (
        <div className="mt-7 flex justify-end">
          <Pagination
            current={currentPage}
            pageSize={itemsPerPage}
            total={itemCount}
            showSizeChanger={false}
            onChange={onPageChange}
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
