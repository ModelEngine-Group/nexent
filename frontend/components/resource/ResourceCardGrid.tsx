"use client";

import { useEffect, useMemo } from "react";
import { Empty, Pagination } from "antd";
import type { ReactNode } from "react";

interface ResourceCardGridProps<T> {
  items: T[];
  page: number;
  pageSize: number;
  onPageChange: (page: number) => void;
  headerItem?: ReactNode;
  emptyState?: ReactNode;
  renderItem: (item: T) => ReactNode;
}

export default function ResourceCardGrid<T>({
  items,
  page,
  pageSize,
  onPageChange,
  headerItem,
  emptyState = <Empty />,
  renderItem,
}: ResourceCardGridProps<T>) {
  const totalPages = Math.max(1, Math.ceil(items.length / pageSize));
  const visibleItems = useMemo(
    () => items.slice((page - 1) * pageSize, page * pageSize),
    [items, page, pageSize]
  );

  useEffect(() => {
    if (page > totalPages) onPageChange(totalPages);
  }, [onPageChange, page, totalPages]);

  return (
    <>
      <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
        {headerItem}
        {items.length === 0 ? (
          <div className="flex min-h-[220px] items-center justify-center sm:col-span-2">
            {emptyState}
          </div>
        ) : (
          visibleItems.map(renderItem)
        )}
      </div>
      {items.length > 0 && totalPages > 1 ? (
        <div className="mt-7 flex justify-end">
          <Pagination
            current={page}
            pageSize={pageSize}
            total={items.length}
            showSizeChanger={false}
            onChange={onPageChange}
          />
        </div>
      ) : null}
    </>
  );
}
