// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { ApiError } from "@/services/api";

/**
 * AIDP reports a duplicate resource name as business code 1022. The BFF
 * forwards that code verbatim in the error details.
 */
export const isAidpDuplicateError = (error: unknown): boolean =>
  error instanceof ApiError && error.details?.upstream_code === 1022;

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
