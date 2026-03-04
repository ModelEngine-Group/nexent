/**
 * Error message utility with i18n support.
 *
 * This module provides functions to get localized error messages by error code.
 */

import { message } from "antd";
import { useTranslation } from "react-i18next";
import { ErrorCode } from "./errorCode";
import { DEFAULT_ERROR_MESSAGES } from "./errorMessage";
import { handleSessionExpired } from "@/lib/session";
import { isSessionExpired } from "./errorCode";
import log from "@/lib/logger";

/**
 * Get error message by error code with i18n support.
 *
 * This function tries to get the message from i18n translation files first,
 * then falls back to default English messages.
 *
 * @param code - The error code
 * @param t - Optional translation function (if not provided, returns default message)
 * @returns The localized error message
 */
export const getI18nErrorMessage = (
  code: string | number,
  t?: (key: string) => string
): string => {
  // Try i18n translation first
  if (t) {
    const i18nKey = `errorCode.${code}`;
    const translated = t(i18nKey);
    // Check if translation exists (i18next returns the key if not found)
    if (translated !== i18nKey) {
      return translated;
    }
  }

  // Fall back to default message
  return (
    DEFAULT_ERROR_MESSAGES[code] ||
    DEFAULT_ERROR_MESSAGES[ErrorCode.UNKNOWN_ERROR]
  );
};

/**
 * Hook to get error message with i18n support.
 *
 * @returns A function that takes an error code and returns the localized message
 */
export const useErrorMessage = () => {
  const { t } = useTranslation();

  return (code: string | number) => getI18nErrorMessage(code, t);
};

/**
 * Handle API error and return user-friendly message.
 *
 * @param error - The error object (can be ApiError, Error, or any)
 * @param t - Optional translation function
 * @returns User-friendly error message
 */
export const handleApiError = (
  error: any,
  t?: (key: string) => string
): string => {
  // Handle ApiError with code
  if (error && typeof error === "object" && "code" in error) {
    return getI18nErrorMessage(error.code as string | number, t);
  }

  // Handle standard Error
  if (error instanceof Error) {
    return error.message;
  }

  // Handle unknown error
  return getI18nErrorMessage(ErrorCode.UNKNOWN_ERROR, t);
};

/**
 * Options for showing error to user
 */
export interface ShowErrorOptions {
  /** Whether to handle session expiration */
  handleSession?: boolean;
  /** Whether to show error message (default: true) */
  showMessage?: boolean;
  /** Custom error message (overrides auto-detected message) */
  customMessage?: string;
  /** Callback after error is shown */
  onError?: (error: any) => void;
}

/**
 * Show error to user with i18n support.
 *
 * This is a convenience function that:
 * 1. Extracts the error code from the error object
 * 2. Gets the i18n translated message
 * 3. Shows the message to user via antd message
 * 4. Optionally handles session expiration
 *
 * @param error - The error object (ApiError, Error, or any)
 * @param t - Translation function (optional, will use default if not provided)
 * @param options - Additional options
 *
 * @example
 * // Simple usage
 * showErrorToUser(error);
 *
 * @example
 * // With translation function
 * const { t } = useTranslation();
 * showErrorToUser(error, t);
 *
 * @example
 * // With options
 * showErrorToUser(error, t, { handleSession: true, onError: (e) => console.log(e) });
 */
export const showErrorToUser = (
  error: any,
  t?: (key: string) => string,
  options: ShowErrorOptions = {}
): void => {
  const {
    handleSession = true,
    showMessage = true,
    customMessage,
    onError,
  } = options;

  // Get error code if available
  let errorCode: number | undefined;
  if (error && typeof error === "object" && "code" in error) {
    errorCode = error.code as number;
  }

  // Handle session expiration
  if (handleSession && errorCode && isSessionExpired(errorCode)) {
    handleSessionExpired();
  }

  // Get the error message
  let errorMessage: string;
  if (customMessage) {
    errorMessage = customMessage;
  } else if (errorCode) {
    errorMessage = getI18nErrorMessage(errorCode, t);
  } else if (error instanceof Error) {
    errorMessage = error.message;
  } else {
    errorMessage = getI18nErrorMessage(ErrorCode.UNKNOWN_ERROR, t);
  }

  // Log the error
  log.error(`Error [${errorCode || "unknown"}]: ${errorMessage}`, error);

  // Show message to user
  if (showMessage) {
    message.error(errorMessage);
  }

  // Call onError callback
  if (onError) {
    onError(error);
  }
};

/**
 * Wrap an async function with automatic error handling.
 *
 * @param fn - The async function to wrap
 * @param options - Error handling options
 * @returns Wrapped function that automatically handles errors
 *
 * @example
 * const safeFetchData = withErrorHandler(async () => {
 *   const result = await api.fetchData();
 *   return result;
 * }, { handleSession: true });
 *
 * // Usage
 * await safeFetchData();
 */
export const withErrorHandler = (
  fn: (...args: any[]) => Promise<any>,
  options: ShowErrorOptions = {}
) => {
  return async (...args: any[]) => {
    try {
      return await fn(...args);
    } catch (error) {
      showErrorToUser(error, undefined, options);
      throw error;
    }
  };
};

/**
 * Check if error requires session refresh action.
 *
 * @param code - The error code
 * @returns True if user needs to re-login
 */
export const requiresSessionRefresh = (code: string | number): boolean => {
  const codeStr = String(code);
  return codeStr === ErrorCode.TOKEN_EXPIRED || codeStr === ErrorCode.TOKEN_INVALID;
};

/**
 * Check if error is a validation error.
 *
 * @param code - The error code
 * @returns True if it's a validation error
 */
export const isValidationError = (code: string | number): boolean => {
  const codeStr = String(code);
  return codeStr >= "000101" && codeStr < "000200";  // 00 Common - 01 Parameter & Validation
};

/**
 * Check if error is a resource not found error.
 *
 * @param code - The error code
 * @returns True if resource not found
 */
export const isNotFoundError = (code: string | number): boolean => {
  const codeStr = String(code);
  return (
    codeStr === ErrorCode.RESOURCE_NOT_FOUND ||
    codeStr === ErrorCode.AGENT_NOT_FOUND ||
    codeStr === ErrorCode.USER_NOT_FOUND ||
    codeStr === ErrorCode.FILE_NOT_FOUND ||
    codeStr === ErrorCode.KNOWLEDGE_NOT_FOUND
  );
};
