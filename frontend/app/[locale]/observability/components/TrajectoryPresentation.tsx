// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { App, Tag } from "antd";
import {
  Bot,
  BrainCircuit,
  Check,
  Copy,
  CodeXml,
  Terminal,
  Settings2,
  Wrench,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { formatMetric, formatTraceTime } from "@/lib/trajectory";
import type { TrajectoryNode } from "@/types/trajectory";

export function trajectoryNodeName(node: TrajectoryNode, t: TFunction): string {
  if (node.kind === "tool" && node.name === "python_interpreter")
    return t("trajectory.tools.python_interpreter", {
      defaultValue: node.name,
    });
  if (node.kind === "tool" && node.name === "code")
    return t("trajectory.tools.code", { defaultValue: node.name });
  if (node.kind !== "phase") return node.name;
  const label = t(`trajectory.phases.${node.name}`, {
    defaultValue: node.name,
  });
  const display = node.attributes["agent.display_name"];
  const agent =
    typeof display === "string" && display.trim()
      ? display.trim()
      : node.attributes["agent.name"];
  return node.name === "memory.prepare" && typeof agent === "string" && agent
    ? `${label} · ${agent}`
    : label;
}

export function NodeIcon({
  kind,
  name,
  large = false,
}: {
  kind: string;
  name?: string;
  large?: boolean;
}) {
  const pythonCall =
    (kind === "phase" && name === "code.execute") ||
    (kind === "tool" && name === "code");
  const Icon = pythonCall
    ? Terminal
    : kind === "tool" && name === "python_interpreter"
      ? CodeXml
      : kind === "agent"
        ? Bot
        : kind === "model"
          ? BrainCircuit
          : kind === "phase"
            ? Settings2
            : Wrench;
  return (
    <span
      className={`trajectory-kind-icon kind-${pythonCall ? "tool" : kind}${large ? " is-large" : ""}`}
      aria-hidden
    >
      <Icon size={large ? 22 : 14} />
    </span>
  );
}

export function TrajectoryStatus({ status }: { status: string }) {
  const { t } = useTranslation();
  const success = status === "success" || status === "completed";
  const error = status === "error" || status === "failed";
  return (
    <Tag
      className={`trajectory-status${success ? " is-success" : error ? " is-error" : ""}`}
      color={success ? "success" : error ? "error" : "default"}
    >
      {success ? <Check size={12} /> : error ? <X size={12} /> : null}
      {t(
        success
          ? "trajectory.success"
          : error
            ? "trajectory.error"
            : ["cancelled", "interrupted"].includes(status)
              ? `trajectory.businessStatus.${status}`
              : `trajectory.availability.${status}`
      )}
    </Tag>
  );
}

export function CopyTraceId({ value }: { value: string }) {
  const { t } = useTranslation();
  const { message } = App.useApp();
  return (
    <button
      className="trajectory-icon-button"
      aria-label={t("trajectory.copyTraceId")}
      onClick={() =>
        void navigator.clipboard.writeText(value).then(
          () => message.success(t("trajectory.copied")),
          () => message.error(t("trajectory.copyFailed"))
        )
      }
    >
      <Copy size={12} />
    </button>
  );
}

export function nodeDuration(value: number | null | undefined): string {
  return value != null && value < 1000
    ? `${formatMetric(value)} ms`
    : `${formatMetric(value == null ? null : value / 1000)} s`;
}

export function nodeTime(value: string | null): string {
  const text = formatTraceTime(value);
  return text === "—"
    ? text
    : `${text}.${String(new Date(value!).getUTCMilliseconds()).padStart(3, "0")}`;
}

function textValue(value: unknown): string {
  if (typeof value === "string") return value.trim();
  if (!value || typeof value !== "object" || Array.isArray(value)) return "";
  const record = value as Record<string, unknown>;
  for (const key of ["text", "value", "content"]) {
    const text = textValue(record[key]);
    if (text) return text;
  }
  return "";
}

export function userInputPreview(value: string | null | undefined): string {
  if (!value) return "";
  let parsed: unknown;
  try {
    parsed = JSON.parse(value);
  } catch {
    const query = value.match(
      /"(?:query|user_input|userInput|question)"\s*:\s*("(?:\\.|[^"\\])*")/
    );
    if (query) {
      try {
        return String(JSON.parse(query[1])).trim();
      } catch {
        return "";
      }
    }
    const text = value.trim();
    return text.startsWith("{") || text.startsWith("[") ? "" : text;
  }
  if (typeof parsed === "string") return parsed.trim();
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return "";
  const record = parsed as Record<string, unknown>;
  for (const key of ["query", "user_input", "userInput", "question"]) {
    const text = textValue(record[key]);
    if (text) return text;
  }
  if (Array.isArray(record.messages)) {
    const message = [...record.messages]
      .reverse()
      .find(
        (item) =>
          !!item &&
          typeof item === "object" &&
          "role" in item &&
          (item as { role?: unknown }).role === "user"
      );
    if (message && typeof message === "object" && "content" in message)
      return textValue((message as { content: unknown }).content);
  }
  return "";
}
