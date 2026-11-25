// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useTranslation } from "react-i18next";
import {
  TrajectoryModelTable,
  TrajectoryModelText,
} from "./TrajectoryModelTable";

type ModelInputMessage = {
  key: number;
  label: string;
  content: string;
  nonTextParts: number;
  toolCalls: number;
};

type ModelInputRow = { key: string; label: string } & (
  | { kind: "messages"; messages: ModelInputMessage[] }
  | { kind: "parameter"; value: string }
);

const MAX_REQUEST_LENGTH = 1024 * 1024;
const MAX_CONTENT_LENGTH = 128 * 1024;
const MAX_MESSAGES = 200;
const MAX_PARAMETERS = 200;

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

export function modelInputRows(source: string): ModelInputRow[] | null {
  if (source.length > MAX_REQUEST_LENGTH) return null;
  let request: unknown;
  try {
    request = JSON.parse(source);
  } catch {
    return null;
  }
  if (!isRecord(request)) return null;
  const { messages, ...parameters } = request;
  const parameterEntries = Object.entries(parameters);
  if (
    !Array.isArray(messages) ||
    !messages.length ||
    messages.length > MAX_MESSAGES ||
    parameterEntries.length > MAX_PARAMETERS
  )
    return null;

  const messageRows: ModelInputMessage[] = [];
  let previewLength = 0;
  for (const message of messages as unknown[]) {
    if (
      !isRecord(message) ||
      typeof message.role !== "string" ||
      !message.role.trim()
    )
      return null;
    let content = "";
    let nonTextParts = 0;
    if (typeof message.content === "string") {
      content = message.content;
    } else if (Array.isArray(message.content)) {
      const textParts: string[] = [];
      for (const part of message.content as unknown[]) {
        if (!isRecord(part) || typeof part.type !== "string") return null;
        if (part.type === "text" || part.type === "input_text") {
          if (typeof part.text !== "string") return null;
          textParts.push(part.text);
        } else {
          nonTextParts += 1;
        }
      }
      content = textParts.join("\n\n");
    } else if (message.content != null) {
      return null;
    }
    previewLength += message.role.length + content.length;
    if (previewLength > MAX_CONTENT_LENGTH) return null;
    messageRows.push({
      key: messageRows.length,
      label: message.role,
      content,
      nonTextParts,
      toolCalls: Array.isArray(message.tool_calls)
        ? message.tool_calls.length
        : 0,
    });
  }
  const rows: ModelInputRow[] = [
    {
      key: "messages",
      label: "messages",
      kind: "messages",
      messages: messageRows,
    },
  ];
  try {
    for (const [name, value] of parameterEntries) {
      rows.push({
        key: name,
        label: name,
        kind: "parameter",
        value: JSON.stringify(value),
      });
    }
  } catch {
    return null;
  }
  return rows;
}

function ModelInputMessages({ messages }: { messages: ModelInputMessage[] }) {
  const { t } = useTranslation();
  return (
    <TrajectoryModelTable
      name={t("trajectory.modelInputMessages")}
      rows={messages}
      nested
      renderValue={({ content, nonTextParts, toolCalls }) => {
        const hasText = Boolean(content.trim());
        return (
          <>
            {hasText && <TrajectoryModelText text={content} />}
            {nonTextParts > 0 && (
              <div>
                {t("trajectory.modelInputNonText", { count: nonTextParts })}
              </div>
            )}
            {toolCalls > 0 && (
              <div>
                {t("trajectory.modelInputToolCalls", { count: toolCalls })}
              </div>
            )}
            {!hasText && !nonTextParts && !toolCalls && "—"}
          </>
        );
      }}
    />
  );
}

export function TrajectoryModelInput({ rows }: { rows: ModelInputRow[] }) {
  const { t } = useTranslation();
  return (
    <TrajectoryModelTable
      name={t("trajectory.modelInput")}
      rows={rows}
      renderValue={(row) =>
        row.kind === "messages" ? (
          <div>
            <ModelInputMessages messages={row.messages} />
          </div>
        ) : (
          <code>{row.value}</code>
        )
      }
    />
  );
}
