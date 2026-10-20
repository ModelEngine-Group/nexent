// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useTranslation } from "react-i18next";

export function SelectedResourceTags({
  items,
  onRemove,
}: {
  items: { id: string; name: string }[];
  onRemove: (id: string) => void;
}) {
  const { t } = useTranslation("common");
  if (!items.length) return null;
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map(({ id, name }) => (
        <span
          key={id}
          className="inline-flex max-w-48 items-center rounded bg-blue-100 px-2 py-0.5 text-sm font-medium text-blue-800"
        >
          <span className="truncate" title={name}>
            {name}
          </span>
          <button
            type="button"
            className="ml-1.5 shrink-0 text-blue-600 hover:text-blue-800"
            aria-label={t("ui.localization.removeResource", { name })}
            onClick={() => onRemove(id)}
          >
            ×
          </button>
        </span>
      ))}
    </div>
  );
}
