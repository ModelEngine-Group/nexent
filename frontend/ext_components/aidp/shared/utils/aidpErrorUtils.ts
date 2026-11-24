// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { ApiError } from "@/services/api";

const upstreamCodeOf = (error: ApiError): string | null => {
  const value = error.details?.upstream_code;
  return typeof value === "number" ||
    (typeof value === "string" && value.trim())
    ? String(value).trim()
    : null;
};

/**
 * AIDP reports a duplicate resource name as business code 1022, sometimes
 * together with HTTP 500. The BFF preserves that code in the error details,
 * so the UI must not rely on the HTTP status alone.
 */
export const isAidpDuplicateError = (error: unknown): boolean =>
  error instanceof ApiError &&
  (String(error.code) === "1022" || upstreamCodeOf(error) === "1022");

/** Resolve errors for a caller-owned inline state or notification. */
export const getAidpErrorMessage = (
  error: unknown,
  translate: (key: string, options: { defaultValue: string }) => string,
  fallbackMessage: string
): string => {
  const message =
    error instanceof Error && error.message ? error.message : fallbackMessage;
  return error instanceof ApiError
    ? translate(`errorCode.${error.code}`, { defaultValue: message })
    : message;
};
