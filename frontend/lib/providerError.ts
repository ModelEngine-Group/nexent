/**
 * Provider Error Utility
 *
 * Centralized error handling and translation for model providers.
 * Provides consistent error messages across different providers (ModelEngine, SiliconFlow, etc.)
 */

import type { TFunction } from "i18next";

/**
 * Error types returned by provider APIs
 */
export type ProviderErrorType =
  | "no_models"
  | "connection_failed"
  | "authentication_failed"
  | "access_denied"
  | "endpoint_not_found"
  | "server_error"
  | "timeout"
  | "ssl_error"
  | "unknown";

/**
 * Provider error information
 */
export interface ProviderError {
  type: ProviderErrorType;
  message: string;
  provider?: string;
  httpCode?: number;
}

/**
 * Provider display names (for error messages)
 */
export const PROVIDER_DISPLAY_NAMES: Record<string, string> = {
  modelengine: "ModelEngine",
  silicon: "SiliconFlow",
  openai: "OpenAI",
  default: "Provider",
};

/**
 * Detect error type from error response or message
 */
export function detectProviderError(errorResponse: unknown): ProviderErrorType {
  if (!errorResponse || typeof errorResponse !== "object") {
    return "unknown";
  }

  const error = errorResponse as Record<string, unknown>;
  const errorCode = error._error as string;
  const errorMessage = ((error._message as string) || "").toLowerCase();
  const httpCode = error.httpCode as number;

  // Check error code first
  if (errorCode) {
    switch (errorCode) {
      case "authentication_failed":
        return "authentication_failed";
      case "access_forbidden":
        return "access_denied";
      case "endpoint_not_found":
        return "endpoint_not_found";
      case "server_error":
        return "server_error";
      case "connection_failed":
        return "connection_failed";
      case "timeout":
        return "timeout";
      case "ssl_error":
        return "ssl_error";
    }
  }

  // Check HTTP status code
  if (httpCode) {
    if (httpCode === 401) {
      return "authentication_failed";
    } else if (httpCode === 403) {
      return "access_denied";
    } else if (httpCode === 404) {
      return "endpoint_not_found";
    } else if (httpCode >= 500) {
      return "server_error";
    } else if (httpCode >= 400) {
      return "connection_failed";
    }
  }

  // Check error message patterns
  if (
    errorMessage.includes("authentication") ||
    errorMessage.includes("invalid api key") ||
    errorMessage.includes("unauthorized")
  ) {
    return "authentication_failed";
  }

  if (
    errorMessage.includes("access denied") ||
    errorMessage.includes("forbidden") ||
    errorMessage.includes("permission")
  ) {
    return "access_denied";
  }

  if (
    errorMessage.includes("endpoint") ||
    errorMessage.includes("not found") ||
    errorMessage.includes("404")
  ) {
    return "endpoint_not_found";
  }

  if (errorMessage.includes("timeout") || errorMessage.includes("timed out")) {
    return "timeout";
  }

  if (errorMessage.includes("ssl") || errorMessage.includes("certificate")) {
    return "ssl_error";
  }

  if (
    errorMessage.includes("server error") ||
    errorMessage.includes("http 5")
  ) {
    return "server_error";
  }

  if (
    errorMessage.includes("connection") ||
    errorMessage.includes("network") ||
    errorMessage.includes("failed to connect")
  ) {
    return "connection_failed";
  }

  return "unknown";
}

/**
 * Translate provider error to user-friendly message
 */
export function translateProviderError(
  error: ProviderError,
  provider: string,
  t: TFunction
): string {
  const displayName =
    PROVIDER_DISPLAY_NAMES[provider.toLowerCase()] ||
    PROVIDER_DISPLAY_NAMES.default;

  switch (error.type) {
    case "no_models":
      return t("model.dialog.error.provider.noModels", {
        provider: displayName,
      });

    case "authentication_failed":
      return t("model.dialog.error.provider.authenticationFailed", {
        provider: displayName,
      });

    case "access_denied":
      return t("model.dialog.error.provider.accessDenied");

    case "endpoint_not_found":
      return t("model.dialog.error.provider.endpointNotFound");

    case "server_error":
      return t("model.dialog.error.provider.serverError", {
        provider: displayName,
        code: error.httpCode || 500,
      });

    case "timeout":
      return t("model.dialog.error.provider.timeout");

    case "ssl_error":
      return t("model.dialog.error.provider.sslError");

    case "connection_failed":
      return t("model.dialog.error.provider.connectionFailed", {
        provider: displayName,
      });

    case "unknown":
    default:
      // Use the original message if available, otherwise use generic connection failed
      if (error.message) {
        return error.message;
      }
      return t("model.dialog.error.provider.connectionFailed", {
        provider: displayName,
      });
  }
}

/**
 * Process provider API response and return user-friendly error if applicable
 */
export function processProviderResponse<T extends Record<string, unknown>>(
  response: T[],
  provider: string,
  t: TFunction
): { models: T[]; error?: string } {
  // Check if response contains error indicator
  if (response && response.length > 0 && response[0]._error) {
    const errorType = detectProviderError(response[0]);
    const error: ProviderError = {
      type: errorType,
      message: response[0]._message as string,
      provider,
      httpCode: response[0].httpCode as number,
    };
    return {
      models: [],
      error: translateProviderError(error, provider, t),
    };
  }

  // Check for empty response (successful call but no models)
  if (!response || response.length === 0) {
    return {
      models: [],
      error: translateProviderError(
        { type: "no_models", message: "" },
        provider,
        t
      ),
    };
  }

  return { models: response };
}
