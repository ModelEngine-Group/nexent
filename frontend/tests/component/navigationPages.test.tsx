// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect, test } from "vitest";
import { resolveAccessibleRoutes } from "@/lib/navigationPages";

test.each([
  ["ops-dashboard", "/ops/dashboard"],
  ["ops-configuration", "/ops/configuration"],
  ["/ops/dashboard", "/ops/dashboard"],
  ["/resource-manage", "/resource-manage"],
  ["/", "/"],
])("resolves page %s to route %s", (pageId, route) => {
  expect(resolveAccessibleRoutes([pageId])).toEqual([route]);
});

test("mixed identifiers and legacy paths preserve order without duplicate routes", () => {
  const pages = [
    "/agents",
    "ops-configuration",
    "/ops/dashboard",
    "ops-dashboard",
    "/ops/configuration",
    "ops-configuration",
  ];
  const snapshot = [...pages];
  expect(resolveAccessibleRoutes(pages)).toEqual([
    "/agents",
    "/ops/configuration",
    "/ops/dashboard",
  ]);
  expect(pages).toEqual(snapshot);
});

test.each([
  { pages: [] },
  { pages: [""] },
  { pages: ["ops-dashboar"] },
  { pages: ["constructor"] },
  { pages: ["__proto__"] },
])(
  "missing and unknown page identifiers grant no routes: $pages",
  ({ pages }) => {
    expect(resolveAccessibleRoutes(pages)).toEqual([]);
  }
);
