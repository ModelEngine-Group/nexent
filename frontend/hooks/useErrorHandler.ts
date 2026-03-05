/**
 * Custom hook for handling API errors with i18n support.
 *
 * This hook provides utilities to:
 * - Convert error codes to localized messages
 * - Handle session expiration
 * - Provide consistent error handling across the app
 */

import { useCallback } from "react";
import { useTranslation } from "react-i18next";
import { message } from "antd";

import { ErrorCode, isSessionExpired } from "@/const/errorCode";
import { DEFAULT_ERROR_MESSAGES } from "@/const/errorMessage";
import { ApiError } from "@/services/api";
import { handleSessionExpired } from "@/lib/session";
import log from "@/lib/logger";

/**
 * Options for error handling
 */
export interface ErrorHandlerOptions {
  /** Whether to show error message to user */
  showMessage?: boolean;
  /** Custom error message key prefix */
  messagePrefix?: string;
  /** Callback on error */
  onError?: (error: Error) => void;
  /** Whether to handle session expiration */
  handleSession?: boolean;
}

/**
 * Default error handler options
 */
const DEFAULT_OPTIONS: ErrorHandlerOptions = {
  showMessage: true,
  handleSession: true,
};

/**
 * Hook for handling API errors with i18n support
 */
export const useErrorHandler = () => {
  const { t } = useTranslation();

  /**
   * Get i18n error message by error code
   */
  const getI18nErrorMessage = useCallback(
    (code: string | number): string => {
      // Try to get i18n key
      const i18nKey = `errorCode.${code}`;
      const translated = t(i18nKey);

      // If translation exists (not equal to key), return translated message
      if (translated !== i18nKey) {
        return translated;
      }

      // Fallback to default messages
      return (
        DEFAULT_ERROR_MESSAGES[code] ||
        DEFAULT_ERROR_MESSAGES[ErrorCode.UNKNOWN_ERROR]
      );
    },
    [t]
  );

  /**
   * Handle API error
   */
  const handleError = useCallback(
    (error: unknown, options: ErrorHandlerOptions = {}) => {
      const { showMessage, onError, handleSession } = {
        ...DEFAULT_OPTIONS,
        ...options,
      };

      // Handle ApiError
      if (error instanceof ApiError) {
        // Handle session expiration
        if (handleSession && isSessionExpired(error.code)) {
          handleSessionExpired();
        }

        // Get localized message
        const errorMessage = getI18nErrorMessage(error.code);

        // Log error
        log.error(`API Error [${error.code}]: ${errorMessage}`, error);

        // Show message to user
        if (showMessage) {
          message.error(errorMessage);
        }

        // Call onError callback
        if (onError) {
          onError(error);
        }

        return {
          code: error.code,
          message: errorMessage,
          originalError: error,
        };
      }

      // Handle unknown error
      if (error instanceof Error) {
        log.error("Unknown error:", error);

        if (showMessage) {
          message.error(getI18nErrorMessage(ErrorCode.UNKNOWN_ERROR));
        }

        if (onError) {
          onError(error);
        }

        return {
          code: ErrorCode.UNKNOWN_ERROR,
          message: getI18nErrorMessage(ErrorCode.UNKNOWN_ERROR),
          originalError: error,
        };
      }

      // Handle non-Error objects
      log.error("Non-error object thrown:", error);

      if (showMessage) {
        message.error(getI18nErrorMessage(ErrorCode.UNKNOWN_ERROR));
      }

      return {
        code: ErrorCode.UNKNOWN_ERROR,
        message: getI18nErrorMessage(ErrorCode.UNKNOWN_ERROR),
        originalError: null,
      };
    },
    [getI18nErrorMessage]
  );

  /**
   * Wrap async function with error handling
   */
  const withErrorHandler = useCallback(
    (fn: (...args: any[]) => Promise<any>, options: ErrorHandlerOptions = {}) => {
      return async (...args: any[]) => {
        try {
          return await fn(...args);
        } catch (error) {
          throw handleError(error, options);
        }
      };
    },
    [handleError]
  );

  return {
    getI18nErrorMessage,
    handleError,
    withErrorHandler,
  };
};
