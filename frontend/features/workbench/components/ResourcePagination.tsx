// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { Pagination } from "antd";

export const RESOURCE_PAGE_SIZE = 10;

export function resourcePage<T>(
  items: T[],
  page: number,
  pageSize = RESOURCE_PAGE_SIZE
): T[] {
  const current = Math.min(
    page,
    Math.max(1, Math.ceil(items.length / pageSize))
  );
  return items.slice((current - 1) * pageSize, current * pageSize);
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
