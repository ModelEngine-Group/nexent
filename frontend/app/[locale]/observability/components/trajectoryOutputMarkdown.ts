// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

export type MarkdownOutputKind = "agent" | "model" | "tool" | "phase";
type JsonObject = Record<string, unknown>;
type TableLabels = {
  field: string;
  value: string;
  index: string;
  logs: string;
};

const MAX_MARKDOWN_LENGTH = 128 * 1024;
const MAX_TABLE_ROWS = 200;
const MAX_TABLE_COLUMNS = 32;

export function isMarkdownOutputKind(kind: string): kind is MarkdownOutputKind {
  return (
    kind === "agent" || kind === "model" || kind === "tool" || kind === "phase"
  );
}

function asObject(value: unknown): JsonObject | undefined {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as JsonObject)
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

function modelMarkdown(value: unknown): string {
  const response = asObject(value);
  if (!response) return "";
  if (!Array.isArray(response.choices))
    return responseText(response.content_parts);
  return response.choices
    .map((item) => {
      const choice = asObject(item);
      const message = responseText(asObject(choice?.message)?.content);
      return message.trim()
        ? message
        : responseText(asObject(choice?.delta)?.content);
    })
    .filter((text) => text.trim())
    .join("\n\n---\n\n");
}

function tableCell(value: unknown): string {
  const text =
    typeof value === "string" ? value : (JSON.stringify(value) ?? "—");
  return text
    .replace(/\r\n|\r|\n/g, "\\n")
    .replace(
      /[&<>|\\`*_[\]~:.@]/g,
      (character) => `&#${character.charCodeAt(0)};`
    );
}

function table(headers: string[], rows: unknown[][]): string {
  if (!rows.length || rows.length > MAX_TABLE_ROWS) return "";
  const line = (cells: unknown[]) => `| ${cells.map(tableCell).join(" | ")} |`;
  return [
    line(headers),
    line(headers.map(() => "---")),
    ...rows.map(line),
  ].join("\n");
}

function jsonTable(value: unknown, labels: TableLabels): string {
  if (!Array.isArray(value)) {
    const record = asObject(value);
    return record
      ? table([labels.field, labels.value], Object.entries(record))
      : "";
  }

  if (!value.length || value.length > MAX_TABLE_ROWS) return "";
  const records = value.map(asObject);
  if (records.every((record) => record !== undefined)) {
    const columns = [...new Set(records.flatMap(Object.keys))];
    if (columns.length > MAX_TABLE_COLUMNS) return "";
    if (columns.length) {
      return table(
        columns,
        records.map((record) =>
          columns.map((column) =>
            Object.hasOwn(record, column) ? record[column] : undefined
          )
        )
      );
    }
  }
  return table(
    [labels.index, labels.value],
    value.map((item, index) => [index + 1, item])
  );
}

function phaseMarkdown(value: unknown, labels: TableLabels): string {
  const record = asObject(value);
  if (record) {
    const fields = Object.keys(record);
    if (
      fields.length === 1 &&
      fields[0] === "steps" &&
      Array.isArray(record.steps)
    )
      return jsonTable(record.steps, labels);
    if (
      fields.length === 2 &&
      Object.hasOwn(record, "output") &&
      typeof record.logs === "string"
    ) {
      const { output, logs } = record;
      const structured = Array.isArray(output)
        ? output.length > 0
        : Object.keys(asObject(output) ?? {}).length > 0;
      const result = jsonTable(structured ? output : { output }, labels);
      if (!result || !logs.trim()) return result;
      const logBlock = logs
        .split(/\r\n|\r|\n/)
        .map((line) => `    ${line}`)
        .join("\n");
      return `${result}\n\n### ${labels.logs}\n\n${logBlock}`;
    }
  }
  return jsonTable(value, labels);
}

function bounded(text: string): string {
  return text.length <= MAX_MARKDOWN_LENGTH && text.trim() ? text : "";
}

export function outputMarkdown(
  source: string,
  kind: MarkdownOutputKind,
  labels: TableLabels
): string {
  if (kind !== "model" && source.length > MAX_MARKDOWN_LENGTH) return "";
  let safeNumbers = true;
  try {
    const value: unknown = JSON.parse(
      source,
      kind === "model"
        ? undefined
        : (_key, value: unknown) => {
            if (
              typeof value === "number" &&
              (!Number.isFinite(value) ||
                (Number.isInteger(value) && !Number.isSafeInteger(value)))
            ) {
              safeNumbers = false;
            }
            return value;
          }
    );
    if (typeof value === "string") return bounded(value);
    if (kind === "model") return bounded(modelMarkdown(value));
    if (!safeNumbers) return "";
    return bounded(
      kind === "phase" ? phaseMarkdown(value, labels) : jsonTable(value, labels)
    );
  } catch (error) {
    return error instanceof SyntaxError ? bounded(source) : "";
  }
}
