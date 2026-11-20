// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { ApiError } from "@/services/api";

const upstreamCodeOf = (error: ApiError): string | null => {
  const value = error.details?.upstream_code;
  return typeof value === "number" ||
    (typeof value === "string" && value.trim())
    ? String(value).trim()
    : null;
};

/** AIDP code 1089 means a file or folder name already exists in that location. */
export const isAidpNameConflictError = (error: unknown): boolean =>
  error instanceof ApiError &&
  (String(error.code) === "1089" || upstreamCodeOf(error) === "1089");

/** Resolve errors for a caller-owned inline state or notification. */
export const getAidpErrorMessage = (
  error: unknown,
  translate: (key: string, options: { defaultValue: string }) => string,
  fallbackMessage: string
): string => {
  const message =
    error instanceof Error && error.message ? error.message : fallbackMessage;
  if (!(error instanceof ApiError)) return message;

  const upstreamCode = upstreamCodeOf(error);
  if (upstreamCode) {
    return translate(`errorCode.${upstreamCode}`, { defaultValue: message });
  }
  return translate(`errorCode.${error.code}`, { defaultValue: message });
};

/**
 * AIDP reports a normalised duplicate word as `error.code=1022`, sometimes
 * together with HTTP 500. The Nexent proxy preserves that business code, so
 * the UI must not rely on the HTTP status alone.
 */
export const isAidpDuplicateWordError = (error: unknown): boolean => {
  if (!(error instanceof ApiError)) return false;
  const upstreamCode = error.details?.upstream_code;
  return String(error.code) === "1022" || String(upstreamCode) === "1022";
};
