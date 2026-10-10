import type { AidpUploadFailedItem } from "./aidpKnowledgeService";
import { ApiError } from "@/services/api";

const asRecord = (value: unknown): Record<string, unknown> | undefined =>
  value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;

/** Preserve business codes and upstream reasons for both upload transports. */
export const parseAidpUploadError = (
  status: number,
  statusText: string,
  responseText: string
): ApiError => {
  let payload: unknown;
  try {
    payload = JSON.parse(responseText);
  } catch {
    return new ApiError(status, responseText || statusText || `HTTP ${status}`);
  }

  const body = asRecord(payload);
  const error = asRecord(body?.detail) || asRecord(body?.message) || body;
  const details = asRecord(error?.details);
  const code = error?.code;
  const message = [
    details?.upstream_reason,
    error?.message,
    body?.detail,
    body?.message,
    payload,
  ].find((value) => typeof value === "string" && value.trim());

  return new ApiError(
    typeof code === "number" || (typeof code === "string" && code.trim())
      ? code
      : status,
    typeof message === "string"
      ? message.trim()
      : responseText || statusText || `HTTP ${status}`,
    details
  );
};

/** Resolve row text without triggering a page-level notification. */
export { getAidpErrorMessage as getAidpUploadErrorMessage } from "./aidpErrorUtils";

export const getAidpUploadFailureDetails = (
  failedList: AidpUploadFailedItem[],
  language: string,
  fallbackMessage: string
) => {
  const isChinese = language.startsWith("zh");
  return failedList.map((item) => {
    const reason = isChinese
      ? item.reason_zh || item.reason_en
      : item.reason_en || item.reason_zh;
    return `${item.file_name}: ${reason || fallbackMessage}`;
  });
};
