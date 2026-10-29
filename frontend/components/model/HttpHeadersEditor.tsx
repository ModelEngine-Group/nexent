// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useRef, useState } from "react";
import { Input } from "antd";
import { useTranslation } from "react-i18next";
import { StandardButton } from "@/components/common/StandardButton";

/** Null means retain a named stored header; response values never reach this editor. */
export function HttpHeadersEditor({
  value,
  onChange,
  onValidityChange,
  disabled,
}: {
  value: Record<string, string | null>;
  onChange: (value: Record<string, string | null>) => void;
  onValidityChange?: (valid: boolean) => void;
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  const sequence = useRef(0);
  const [rows, setRows] = useState(() =>
    Object.entries(value).map(([name, value]) => ({
      id: ++sequence.current,
      name,
      value,
    }))
  );
  function update(next: typeof rows) {
    setRows(next);
    const names = next.map((row) => row.name.toLowerCase());
    const valid =
      next.every((row) => /^[!#$%&'*+.^_`|~0-9A-Za-z-]+$/.test(row.name)) &&
      new Set(names).size === names.length;
    onValidityChange?.(valid);
    if (valid)
      onChange(
        Object.fromEntries(
          next.map((row) => [row.name.toLowerCase(), row.value])
        )
      );
  }
  return (
    <div className="space-y-2">
      {rows.map((row) => (
        <div key={row.id} className="flex gap-2">
          <Input
            aria-label={t("modelProfile.headerName")}
            value={row.name}
            disabled={disabled}
            onChange={(event) =>
              update(
                rows.map((item) =>
                  item.id === row.id
                    ? { ...item, name: event.target.value }
                    : item
                )
              )
            }
          />
          <Input.Password
            aria-label={t("modelProfile.headerValue")}
            value={row.value ?? ""}
            placeholder={
              row.value === null ? t("modelProfile.storedHeader") : ""
            }
            visibilityToggle={row.value !== null && !!row.value}
            disabled={disabled}
            onChange={(event) =>
              update(
                rows.map((item) =>
                  item.id === row.id
                    ? { ...item, value: event.target.value }
                    : item
                )
              )
            }
          />
          <StandardButton
            disabled={disabled}
            onClick={() => update(rows.filter((item) => item.id !== row.id))}
          >
            {t("common.delete")}
          </StandardButton>
        </div>
      ))}
      <StandardButton
        disabled={disabled}
        onClick={() =>
          update([...rows, { id: ++sequence.current, name: "", value: "" }])
        }
      >
        {t("modelProfile.addHeader")}
      </StandardButton>
    </div>
  );
}
