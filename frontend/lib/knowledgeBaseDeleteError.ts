// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { ErrorCode } from "@/const/errorCode";
import type { KnowledgeReferenceConflictDetails } from "@/types/knowledgeResource";

type Translate = (key: string, options?: Record<string, unknown>) => string;

type BlockingFile = {
  file_name?: unknown;
  status?: unknown;
};

/** Format a knowledge-base deletion error without losing EDS details. */
export function formatKnowledgeBaseDeleteError(
  error: unknown,
  t: Translate,
  fallbackKey: string
): string {
  if (isErrorCode(error, ErrorCode.KNOWLEDGE_DELETE_BLOCKED)) {
    const details = getDetails(error);
    const files = Array.isArray(details?.blocking_files)
      ? (details.blocking_files as BlockingFile[])
      : [];
    const fileLabels = files
      .map((file) => {
        const name = String(file.file_name || "").trim();
        const status = String(file.status || "").trim();
        return name ? (status ? `${name} (${status})` : name) : "";
      })
      .filter(Boolean);

    return fileLabels.length > 0
      ? t("knowledgeBase.message.deleteBlockedWithFiles", {
          files: fileLabels.join(", "),
        })
      : t("knowledgeBase.message.deleteBlocked");
  }

  if (isErrorCode(error, ErrorCode.KNOWLEDGE_REFERENCED_BY_AGENT)) {
    return t("knowledgeBase.message.deleteBlockedByAgents");
  }

  if (isErrorCode(error, ErrorCode.KNOWLEDGE_RESOURCE_BUSY)) {
    return t("knowledgeBase.message.deleteBusy");
  }

  if (error instanceof Error && error.message) {
    return error.message;
  }
  return t(fallbackKey);
}

/** Return whether the error is the agent-reference deletion conflict. */
export function isKnowledgeReferenceConflict(error: unknown): boolean {
  return isErrorCode(error, ErrorCode.KNOWLEDGE_REFERENCED_BY_AGENT);
}

/** Extract the typed reference details from a deletion conflict error. */
export function getKnowledgeReferenceDetails(
  error: unknown
): KnowledgeReferenceConflictDetails | null {
  const details = getDetails(error);
  if (!details || !Array.isArray(details.visible_agents)) {
    return null;
  }
  return {
    reason: "agent_references",
    visible_agents:
      details.visible_agents as KnowledgeReferenceConflictDetails["visible_agents"],
    hidden_agent_count: Number(details.hidden_agent_count ?? 0),
    total_agent_count: Number(details.total_agent_count ?? 0),
  };
}

function isErrorCode(error: unknown, expectedCode: string): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    String((error as { code?: unknown }).code) === expectedCode
  );
}

function getDetails(error: unknown): Record<string, unknown> | undefined {
  if (typeof error !== "object" || error === null || !("details" in error)) {
    return undefined;
  }
  const details = (error as { details?: unknown }).details;
  return typeof details === "object" && details !== null
    ? (details as Record<string, unknown>)
    : undefined;
}
