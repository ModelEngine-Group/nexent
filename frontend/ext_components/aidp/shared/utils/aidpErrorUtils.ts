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
 * AIDP code 1089 (file/folder duplicate) and 1092 (folder-move duplicate)
 * mean that the name already exists in the target location.
 */
const NAME_CONFLICT_CODES = new Set(["1089", "1092"]);

export const isAidpNameConflictError = (error: unknown): boolean => {
  if (!(error instanceof ApiError)) return false;
  const upstreamCode = upstreamCodeOf(error);
  return (
    NAME_CONFLICT_CODES.has(String(error.code)) ||
    (upstreamCode !== null && NAME_CONFLICT_CODES.has(upstreamCode))
  );
};

/** Resolve an upstream message without remapping its business code. */
export const getAidpPlainMessage = (
  error: unknown,
  fallbackMessage: string
): string =>
  error instanceof Error && error.message ? error.message : fallbackMessage;

/** Stable reason codes returned by the ontology binding BFF. */
const AIDP_BINDING_REASON_KEYS: Record<string, string> = {
  ontology_binding_jargon_conflict:
    "aidpKnowledge.ontologyBindingJargonConflict",
  ontology_binding_other_conflict: "aidpKnowledge.ontologyBindingOtherConflict",
};

/** AIDP reports a duplicate resource name as business code 1022. The BFF
 * forwards that code verbatim in the error details.
 */
export const isAidpDuplicateError = (error: unknown): boolean =>
  error instanceof ApiError && error.details?.upstream_code === 1022;

/** Resolve errors for a caller-owned inline state or notification.
 *
 * Only upstream AIDP business codes are translated. Without one, the backend
 * message is authoritative; the Nexent transport code (for example 130501)
 * must not replace the upstream reason with a generic label.
 */
export const getAidpErrorMessage = (
  error: unknown,
  translate: (key: string, options: { defaultValue: string }) => string,
  fallbackMessage: string
): string => {
  const message =
    error instanceof Error && error.message ? error.message : fallbackMessage;
  if (!(error instanceof ApiError)) return message;

  const reason = error.details?.reason;
  const reasonKey =
    typeof reason === "string" ? AIDP_BINDING_REASON_KEYS[reason] : undefined;
  if (reasonKey) {
    return translate(reasonKey, { defaultValue: message });
  }

  const upstreamCode = upstreamCodeOf(error);
  if (upstreamCode) {
    return translate(`errorCode.${upstreamCode}`, { defaultValue: message });
  }
  return message;
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
