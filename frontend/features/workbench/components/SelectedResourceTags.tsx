// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { ReactNode } from "react";

export function SelectedResourceTags({
  items,
  onRemove,
}: {
  items: { id: string; name: string; warning?: ReactNode }[];
  onRemove: (id: string) => void;
}) {
  if (!items.length) return null;
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map(({ id, name, warning }) => (
        <span
          key={id}
          className={`inline-flex max-w-48 items-center rounded px-2 py-0.5 text-sm font-medium ${
            warning
              ? "bg-red-50 text-red-700 ring-1 ring-red-300"
              : "bg-blue-100 text-blue-800"
          }`}
        >
          {warning ? <span className="mr-1 inline-flex">{warning}</span> : null}
          <span className="truncate" title={name}>
            {name}
          </span>
          <button
            type="button"
            className={`ml-1.5 shrink-0 ${
              warning
                ? "text-red-500 hover:text-red-700"
                : "text-blue-600 hover:text-blue-800"
            }`}
            aria-label={`移除 ${name}`}
            onClick={() => onRemove(id)}
          >
            ×
          </button>
        </span>
      ))}
    </div>
  );
}
