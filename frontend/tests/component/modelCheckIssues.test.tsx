// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect, it } from "vitest";
import {
  groupModelCheckIssues,
  modelCheckFailure,
} from "../../lib/modelCheckIssues";
import { ApiError } from "../../services/api";

it.each([
  [
    new ApiError(422, "private", { category: "PARAMETER_INVALID" }),
    "MODEL_REQUEST_INVALID",
    "model",
    undefined,
  ],
  [
    new ApiError(422, "private", { category: "API_PATH_CONFLICT" }),
    "MODEL_REQUEST_INVALID",
    "model",
    undefined,
  ],
  [
    new ApiError(422, "private", { category: "MODEL_HTTP_AUTH_CONFLICT" }),
    "MODEL_HTTP_AUTH_CONFLICT",
    "connection",
    undefined,
  ],
  [
    new ApiError(403, "private"),
    "MODEL_AUTHENTICATION_ERROR",
    "connection",
    403,
  ],
  [new ApiError(404, "private"), "MODEL_HTTP_ERROR", "connection", 404],
  [
    Object.assign(new Error("private"), { code: 502 }),
    "MODEL_HTTP_ERROR",
    "connection",
    502,
  ],
  [new Error("private"), "MODEL_NETWORK_ERROR", "connection", undefined],
])(
  "classifies safe detection failures without exposing raw messages",
  (error, category, scope, status) => {
    const issue = modelCheckFailure(error);
    expect(issue).toEqual({
      category,
      scope,
      ...(status ? { http_status: status } : {}),
    });
    expect(JSON.stringify(issue)).not.toContain("private");
  }
);

it("deduplicates shared connection failures but retains each model parameter failure", () => {
  const common = { category: "MODEL_NOT_FOUND", scope: "connection" as const };
  expect(groupModelCheckIssues({ a: common, b: common })).toEqual({
    shared: [common],
    models: [],
  });
  const parameter = {
    category: "MODEL_REQUEST_INVALID",
    scope: "model" as const,
  };
  const grouped = groupModelCheckIssues({
    a: common,
    b: common,
    c: parameter,
    d: parameter,
  });
  expect(grouped.shared).toHaveLength(1);
  expect(grouped.models.map((item) => item.id)).toEqual(["c", "d"]);
});
