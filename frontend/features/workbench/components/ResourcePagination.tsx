"use client";

import { Pagination } from "antd";

export const RESOURCE_PAGE_SIZE = 4;

export function resourcePage<T>(items: T[], page: number): T[] {
  const current = Math.min(
    page,
    Math.max(1, Math.ceil(items.length / RESOURCE_PAGE_SIZE))
  );
  return items.slice(
    (current - 1) * RESOURCE_PAGE_SIZE,
    current * RESOURCE_PAGE_SIZE
  );
}

export function ResourcePagination({
  current,
  total,
  onChange,
  disabled = false,
}: {
  current: number;
  total: number;
  onChange: (page: number) => void;
  disabled?: boolean;
}) {
  return (
    <div className="mt-4 flex justify-center">
      <Pagination
        current={Math.min(
          current,
          Math.max(1, Math.ceil(total / RESOURCE_PAGE_SIZE))
        )}
        total={total}
        pageSize={RESOURCE_PAGE_SIZE}
        showSizeChanger={false}
        disabled={disabled}
        onChange={onChange}
      />
    </div>
  );
}
