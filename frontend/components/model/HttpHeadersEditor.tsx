// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useEffect, useRef, useState } from "react";
import { Input, Button } from "antd";
import { useTranslation } from "react-i18next";

const snapshotHeaders = (value: Record<string, string | null>) =>
  JSON.stringify(
    Object.entries(value).sort(([left], [right]) => left.localeCompare(right))
  );

const validHeaderNames = (rows: Array<{ name: string }>) => {
  const names = rows.map((row) => row.name.toLowerCase());
  return (
    rows.every((row) => /^[!#$%&'*+.^_`|~0-9A-Za-z-]+$/.test(row.name)) &&
    new Set(names).size === names.length
  );
};

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
  const snapshot = snapshotHeaders(value);
  const externalSnapshot = useRef(snapshot);
  const emittedSnapshot = useRef(snapshot);
  useEffect(() => {
    if (snapshot === externalSnapshot.current) return;
    externalSnapshot.current = snapshot;
    if (snapshot === emittedSnapshot.current) return;
    emittedSnapshot.current = snapshot;
    const next = Object.entries(value).map(([name, value]) => ({
      id: ++sequence.current,
      name,
      value,
    }));
    setRows(next);
    onValidityChange?.(validHeaderNames(next));
  }, [snapshot, value, onValidityChange]);

  function update(next: typeof rows) {
    setRows(next);
    const valid = validHeaderNames(next);
    onValidityChange?.(valid);
    if (valid) {
      const updated = Object.fromEntries(
        next.map((row) => [row.name.toLowerCase(), row.value])
      );
      emittedSnapshot.current = snapshotHeaders(updated);
      onChange(updated);
    }
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
          <Button
            disabled={disabled}
            onClick={() => update(rows.filter((item) => item.id !== row.id))}
          >
            {t("common.delete")}
          </Button>
        </div>
      ))}
      <Button
        disabled={disabled}
        onClick={() =>
          update([...rows, { id: ++sequence.current, name: "", value: "" }])
        }
      >
        {t("modelProfile.addHeader")}
      </Button>
    </div>
  );
}
