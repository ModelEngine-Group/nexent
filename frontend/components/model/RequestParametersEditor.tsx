// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useEffect, useRef, useState } from "react";
import { Alert, Input, InputNumber, Select, Switch } from "antd";
import { Plus, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { StandardButton } from "@/components/common/StandardButton";

type Kind = "string" | "number" | "boolean" | "object" | "array" | "null";
interface Row {
  id: number;
  key: string;
  kind: Kind;
  value: unknown;
  children: Row[];
}
let sequence = 0;
const escapeKey = (key: string) =>
  key.replaceAll("~", "~0").replaceAll("/", "~1");
function row(key: string, value: unknown = ""): Row {
  const kind: Kind =
    value === null
      ? "null"
      : Array.isArray(value)
        ? "array"
        : typeof value === "object"
          ? "object"
          : typeof value === "number"
            ? "number"
            : typeof value === "boolean"
              ? "boolean"
              : "string";
  return {
    id: ++sequence,
    key,
    kind,
    value,
    children:
      kind === "object"
        ? Object.entries(value as Record<string, unknown>).map(([k, v]) =>
            row(k, v)
          )
        : kind === "array"
          ? (value as unknown[]).map((v) => row("", v))
          : [],
  };
}
function parseRow(item: Row): unknown {
  if (item.kind === "object")
    return Object.fromEntries(parseRows(item.children, false));
  if (item.kind === "array") return item.children.map(parseRow);
  if (item.kind === "null") return null;
  if (
    item.kind === "number" &&
    (typeof item.value !== "number" || !Number.isFinite(item.value))
  )
    throw Error("invalid number");
  return item.value;
}
function parseRows(rows: Row[], paths: boolean): Array<[string, unknown]> {
  const used = new Set<string>();
  return rows.map((item) => {
    const key = paths
      ? item.key.startsWith("/")
        ? item.key
        : "/" + escapeKey(item.key)
      : item.key;
    if (!item.key.trim() || used.has(key)) throw Error("invalid key");
    used.add(key);
    return [key, parseRow(item)];
  });
}
export function parseRequestParameters(
  value: string
): Array<{ path: string; value: unknown }> | null {
  try {
    const parsed: unknown = JSON.parse(value);
    return Array.isArray(parsed) &&
      parsed.every(
        (entry) =>
          entry &&
          typeof entry === "object" &&
          typeof entry.path === "string" &&
          Object.hasOwn(entry, "value")
      )
      ? parsed
      : null;
  } catch {
    return null;
  }
}

function fromJson(value: string): Row[] {
  return (parseRequestParameters(value) ?? []).map((entry) => {
    const parts = entry.path.slice(1).split("/");
    const decoded = parts[0].replaceAll("~1", "/").replaceAll("~0", "~");
    return row(
      parts.length === 1 && !decoded.startsWith("/") ? decoded : entry.path,
      entry.value
    );
  });
}

/** Keep typed drafts local, including empty and duplicate keys, until they are valid. */
export function RequestParametersEditor({
  value,
  onChange,
  disabled = false,
  onValidityChange,
}: {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  onValidityChange?: (valid: boolean) => void;
}) {
  const { t } = useTranslation();
  const [rows, setRows] = useState(() => fromJson(value));
  const emitted = useRef(value);
  const [invalid, setInvalid] = useState(false);
  useEffect(() => {
    if (value !== emitted.current) {
      setRows(fromJson(value));
      setInvalid(false);
      onValidityChange?.(true);
      emitted.current = value;
    }
  }, [value, onValidityChange]);
  const update = (next: Row[]) => {
    setRows(next);
    try {
      const serialized = JSON.stringify(
        parseRows(next, true).map(([path, val]) => ({ path, value: val }))
      );
      emitted.current = serialized;
      setInvalid(false);
      onValidityChange?.(true);
      onChange(serialized);
    } catch {
      setInvalid(true);
      onValidityChange?.(false);
    }
  };
  return (
    <div
      className="space-y-3"
      role="group"
      aria-label={t("modelProfile.extraParameters")}
    >
      <p className="text-xs text-muted-foreground">
        {t("modelProfile.extraHelp")}
      </p>
      <Rows rows={rows} onChange={update} disabled={disabled} />
      {invalid && (
        <Alert type="error" title={t("modelProfile.parameterRowsInvalid")} />
      )}
    </div>
  );
}

function Rows({
  rows,
  onChange,
  disabled,
  array = false,
}: {
  rows: Row[];
  onChange: (rows: Row[]) => void;
  disabled: boolean;
  array?: boolean;
}) {
  const { t } = useTranslation();
  const replace = (id: number, patch: Partial<Row>) =>
    onChange(
      rows.map((item) => (item.id === id ? { ...item, ...patch } : item))
    );
  return (
    <div className="space-y-3">
      {rows.length > 0 && (
        <div className="hidden gap-3 text-xs text-muted-foreground md:grid md:grid-cols-[minmax(0,1fr)_120px_minmax(0,1fr)_32px]">
          <span>
            {t(
              array
                ? "modelProfile.parameterIndex"
                : "modelProfile.parameterName"
            )}
          </span>
          <span>{t("modelProfile.parameterType")}</span>
          <span>{t("modelProfile.parameterValue")}</span>
          <span />
        </div>
      )}
      {rows.map((item, index) => (
        <div key={item.id} className="space-y-3">
          <div className="grid grid-cols-1 items-start gap-3 md:grid-cols-[minmax(0,1fr)_120px_minmax(0,1fr)_32px]">
            {array ? (
              <span className="py-1.5 text-sm">{index + 1}</span>
            ) : (
              <Input
                aria-label={`${t("modelProfile.parameterName")} ${index + 1}`}
                placeholder={t("modelProfile.parameterName")}
                value={item.key}
                disabled={disabled}
                onChange={(e) => replace(item.id, { key: e.target.value })}
              />
            )}
            <Select
              aria-label={`${t("modelProfile.parameterType")} ${index + 1}`}
              value={item.kind}
              disabled={disabled}
              getPopupContainer={(trigger) => trigger.parentElement!}
              options={(
                [
                  "string",
                  "number",
                  "boolean",
                  "object",
                  "array",
                  "null",
                ] as Kind[]
              ).map((kind) => ({
                value: kind,
                label: t(`modelProfile.valueType.${kind}`),
              }))}
              onChange={(kind: Kind) =>
                replace(item.id, {
                  kind,
                  value:
                    kind === "number"
                      ? 0
                      : kind === "boolean"
                        ? false
                        : kind === "null"
                          ? null
                          : "",
                  children: [],
                })
              }
            />
            {item.kind === "string" ? (
              <Input
                aria-label={`${t("modelProfile.parameterValue")} ${index + 1}`}
                value={String(item.value)}
                disabled={disabled}
                onChange={(e) => replace(item.id, { value: e.target.value })}
              />
            ) : item.kind === "number" ? (
              <InputNumber
                className="!w-full"
                aria-label={`${t("modelProfile.parameterValue")} ${index + 1}`}
                value={typeof item.value === "number" ? item.value : null}
                disabled={disabled}
                onChange={(v) => replace(item.id, { value: v })}
              />
            ) : item.kind === "boolean" ? (
              <div className="flex h-8 items-center">
                <Switch
                  aria-label={`${t("modelProfile.parameterValue")} ${index + 1}`}
                  checked={item.value === true}
                  disabled={disabled}
                  onChange={(v) => replace(item.id, { value: v })}
                />
              </div>
            ) : (
              <span className="py-1.5 text-sm text-muted-foreground">
                {t(`modelProfile.valueType.${item.kind}`)}
              </span>
            )}
            <StandardButton
              aria-label={`${t("common.delete")} ${index + 1}`}
              disabled={disabled}
              className="!w-8 !px-0"
              icon={<Trash2 size={14} />}
              onClick={() => onChange(rows.filter((r) => r.id !== item.id))}
            />
          </div>
          {(item.kind === "object" || item.kind === "array") && (
            <div className="ml-3 border-l pl-4">
              <Rows
                rows={item.children}
                disabled={disabled}
                array={item.kind === "array"}
                onChange={(children) => replace(item.id, { children })}
              />
            </div>
          )}
        </div>
      ))}
      <StandardButton
        icon={<Plus size={14} />}
        disabled={disabled}
        onClick={() => onChange([...rows, row("")])}
      >
        {t("modelProfile.addParameter")}
      </StandardButton>
    </div>
  );
}
