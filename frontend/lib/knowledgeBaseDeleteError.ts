import { ErrorCode } from "@/const/errorCode";

type Translate = (
  key: string,
  options?: Record<string, unknown>
) => string;

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

  if (error instanceof Error && error.message) {
    return error.message;
  }
  return t(fallbackKey);
}

function isErrorCode(error: unknown, expectedCode: string): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    String((error as { code?: unknown }).code) === expectedCode
  );
}

function getDetails(
  error: unknown
): Record<string, unknown> | undefined {
  if (typeof error !== "object" || error === null || !("details" in error)) {
    return undefined;
  }
  const details = (error as { details?: unknown }).details;
  return typeof details === "object" && details !== null
    ? (details as Record<string, unknown>)
    : undefined;
}
