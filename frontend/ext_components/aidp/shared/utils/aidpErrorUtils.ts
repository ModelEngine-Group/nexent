import { ApiError } from "@/services/api";

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
