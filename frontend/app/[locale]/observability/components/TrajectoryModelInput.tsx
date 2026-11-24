// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useTranslation } from "react-i18next";
import { TrajectoryMarkdown } from "./TrajectoryMarkdown";

type ModelInputMessage = {
  role: string;
  content: string;
  nonTextParts: number;
  toolCalls: number;
};

const MAX_REQUEST_LENGTH = 1024 * 1024;
const MAX_CONTENT_LENGTH = 128 * 1024;
const MAX_MESSAGES = 200;

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

export function modelInputMessages(source: string): ModelInputMessage[] | null {
  if (source.length > MAX_REQUEST_LENGTH) return null;
  let request: unknown;
  try {
    request = JSON.parse(source);
  } catch {
    return null;
  }
  const messages: unknown = isRecord(request) ? request.messages : undefined;
  if (
    !Array.isArray(messages) ||
    !messages.length ||
    messages.length > MAX_MESSAGES
  )
    return null;

  const rows: ModelInputMessage[] = [];
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
    rows.push({
      role: message.role,
      content,
      nonTextParts,
      toolCalls: Array.isArray(message.tool_calls)
        ? message.tool_calls.length
        : 0,
    });
  }
  return rows;
}

export function TrajectoryModelInput({
  messages,
}: {
  messages: ModelInputMessage[];
}) {
  const { t } = useTranslation();
  return (
    <table
      className="trajectory-model-input-table"
      aria-label={t("trajectory.modelInputMessages")}
    >
      <thead>
        <tr>
          <th scope="col">{t("trajectory.markdownIndex")}</th>
          <th scope="col">{t("trajectory.modelInputRole")}</th>
          <th scope="col">{t("trajectory.modelInputContent")}</th>
        </tr>
      </thead>
      <tbody>
        {messages.map(({ role, content, nonTextParts, toolCalls }, index) => (
          <tr key={index}>
            <td>{index + 1}</td>
            <td>{role}</td>
            <td>
              {content.trim() ? <TrajectoryMarkdown text={content} /> : null}
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
              {!content.trim() && !nonTextParts && !toolCalls && "—"}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
