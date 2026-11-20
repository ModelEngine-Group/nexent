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
