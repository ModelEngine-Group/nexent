// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import {
  TrajectoryModelTable,
  TrajectoryModelText,
} from "./TrajectoryModelTable";

type ResultValue = { kind: "markdown" | "json"; text: string };
type ResultRow<Value> = { key: number; label: string; value: Value };
type ModelResultRow = ResultRow<
  ResultValue | { kind: "choices"; rows: ResultRow<ResultValue>[] }
>;

const MAX_RESULT_LENGTH = 1024 * 1024;
const MAX_TEXT_LENGTH = 128 * 1024;
const MAX_ROWS = 200;
const TEXT_FIELDS = new Set([
  "content",
  "content_parts",
  "reasoning",
  "reasoning_content",
  "reasoning_parts",
  "refusal",
]);

function asObject(value: unknown): Record<string, unknown> | undefined {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

function responseText(value: unknown): string {
  if (typeof value === "string") return value;
  if (!Array.isArray(value)) return "";
  return value
    .map((item) => {
      const part = asObject(item);
      return part?.type === "text" && typeof part.text === "string"
        ? part.text
        : "";
    })
    .join("");
}

function fieldValue(field: string, value: unknown): ResultValue {
  const text = TEXT_FIELDS.has(field) ? responseText(value) : "";
  return text.trim()
    ? { kind: "markdown", text }
    : { kind: "json", text: JSON.stringify(value) };
}

function choiceRows(choices: unknown[]): ResultRow<ResultValue>[] {
  const rows: ResultRow<ResultValue>[] = [];
  for (const [index, choice] of choices.entries()) {
    const record = asObject(choice);
    const fields =
      record && Object.keys(record).length
        ? Object.entries(record).flatMap(
            ([field, value]): [string, unknown][] => {
              const message =
                field === "message" || field === "delta"
                  ? asObject(value)
                  : undefined;
              return message && Object.keys(message).length
                ? Object.entries(message)
                : [[field, value]];
            }
          )
        : [["choice", choice] as const];
    for (const [field, value] of fields) {
      rows.push({
        key: rows.length,
        label: choices.length > 1 ? `${index + 1}. ${field}` : field,
        value: fieldValue(field, value),
      });
      if (rows.length > MAX_ROWS) return rows;
    }
  }
  return rows;
}

export function modelResultRows(
  source: string,
  slot: "output" | "reasoning"
): ModelResultRow[] | null {
  if (!source.trim() || source.length > MAX_RESULT_LENGTH) return null;
  let result: unknown;
  try {
    result = JSON.parse(source);
  } catch {
    result = source;
  }

  if (result == null || (typeof result === "string" && !result.trim()))
    return null;
  const record = asObject(result);
  const fields: [string, unknown][] = record
    ? Object.entries(record)
    : [[slot === "output" ? "content" : "reasoning", result]];
  if (!fields.length || fields.length > MAX_ROWS) return null;

  const rows: ModelResultRow[] = [];
  let rowCount = fields.length;
  let textLength = 0;
  try {
    for (const [label, entry] of fields) {
      if (label === "choices" && Array.isArray(entry) && entry.length) {
        if (entry.length > MAX_ROWS) return null;
        const choices = choiceRows(entry);
        rowCount += choices.length;
        for (const { value } of choices) {
          if (value.kind === "markdown") textLength += value.text.length;
        }
        rows.push({
          key: rows.length,
          label,
          value: { kind: "choices", rows: choices },
        });
      } else {
        const value = fieldValue(label, entry);
        if (value.kind === "markdown") textLength += value.text.length;
        rows.push({ key: rows.length, label, value });
      }
      if (rowCount > MAX_ROWS || textLength > MAX_TEXT_LENGTH) return null;
    }
  } catch {
    return null;
  }
  return rows;
}

function renderValue(value: ResultValue) {
  return value.kind === "markdown" ? (
    <TrajectoryModelText text={value.text} />
  ) : (
    <code>{value.text}</code>
  );
}

export function TrajectoryModelResult({
  rows,
  name,
}: {
  rows: ModelResultRow[];
  name: string;
}) {
  return (
    <TrajectoryModelTable
      name={name}
      rows={rows}
      renderValue={({ label, value }) =>
        value.kind === "choices" ? (
          <div>
            <TrajectoryModelTable
              name={label}
              rows={value.rows}
              nested
              fitContent
              labelWidth={112}
              renderValue={(row) => renderValue(row.value)}
            />
          </div>
        ) : (
          renderValue(value)
        )
      }
    />
  );
}
