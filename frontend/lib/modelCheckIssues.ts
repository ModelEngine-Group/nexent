// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { ModelOutletValidationResponse } from "@/types/modelProfile";
import { ApiError } from "@/services/api";

export type ModelCheckIssue = NonNullable<
  ModelOutletValidationResponse["error"]
>;

export function modelCheckFailure(error: unknown): ModelCheckIssue {
  if (error instanceof ApiError) {
    const category =
      typeof error.details?.category === "string" ? error.details.category : "";
    if (category.startsWith("PARAMETER_") || category.startsWith("API_PATH_"))
      return { category: "MODEL_REQUEST_INVALID", scope: "model" };
    if (
      category === "MODEL_HTTP_HEADERS_INVALID" ||
      category === "MODEL_HTTP_AUTH_CONFLICT"
    )
      return { category, scope: "connection" };
    const code = Number(error.code);
    return {
      category:
        code === 401 || code === 403
          ? "MODEL_AUTHENTICATION_ERROR"
          : "MODEL_HTTP_ERROR",
      scope: "connection",
      ...(code >= 400 && code < 600 ? { http_status: code } : {}),
    };
  }
  if (
    error &&
    typeof error === "object" &&
    "code" in error &&
    typeof error.code === "number"
  ) {
    const code = error.code;
    return {
      category:
        code === 401 || code === 403
          ? "MODEL_AUTHENTICATION_ERROR"
          : "MODEL_HTTP_ERROR",
      scope: "connection",
      ...(code >= 400 && code < 600 ? { http_status: code } : {}),
    };
  }
  return { category: "MODEL_NETWORK_ERROR", scope: "connection" };
}

/** Common HTTP failures are grouped independently of model-specific controls. */
export function groupModelCheckIssues(issues: Record<string, ModelCheckIssue>) {
  const shared = new Map<string, ModelCheckIssue>();
  const models: Array<{ id: string; issue: ModelCheckIssue }> = [];
  for (const [id, issue] of Object.entries(issues)) {
    if (issue.scope === "model") models.push({ id, issue });
    else
      shared.set(
        `${issue.category}:${issue.http_status ?? ""}:${issue.message ?? ""}`,
        issue
      );
  }
  return { shared: [...shared.values()], models };
}
