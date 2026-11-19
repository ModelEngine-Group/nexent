// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { render } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import LegacyRepositoryEntry from "@/app/agent-repository/LegacyRepositoryEntry";
import { buildLegacyRepositoryRedirect } from "@/lib/legacyRepositoryRoutes";

vi.mock("@/base-path.mjs", () => ({ BASE_PATH: "/nexent" }));
const navigation = vi.hoisted(() => ({ replace: vi.fn(), search: "" }));
vi.mock("next/navigation", () => ({
  useParams: () => ({ locale: "zh" }),
  useRouter: () => ({ replace: navigation.replace }),
  useSearchParams: () => new URLSearchParams(navigation.search),
}));

beforeEach(() => {
  navigation.replace.mockReset();
  navigation.search = "";
});

test("redirects the retired agent repository alias to the agent repository tab", () => {
  render(<LegacyRepositoryEntry />);
  expect(navigation.replace).toHaveBeenCalledWith(
    `/nexent/zh/resource-space?tab=agent&view=repository`
  );
});

test("routes agent reviews to the unified review center", () => {
  const href = buildLegacyRepositoryRedirect("en", "tab=review&review_id=42");
  expect(href).toBe(
    `/nexent/en/resource-space?tab=review&review_id=42&resource_type=agent`
  );
});

test("retires the personal agent view by landing on the agent repository", () => {
  navigation.search = "tab=mine&agent_id=42&onboarding=usage-menu";
  render(<LegacyRepositoryEntry />);
  const params = new URL(
    navigation.replace.mock.calls[0][0] as string,
    "http://localhost"
  ).searchParams;
  expect(navigation.replace).toHaveBeenCalledTimes(1);
  expect(params.get("tab")).toBe("agent");
  expect(params.get("view")).toBe("repository");
  // The unified repository rejects the retired onboarding marker outright.
  expect(params.get("onboarding")).toBeNull();
});

test("does not allow stale view and resource type to override the destination", () => {
  expect(
    buildLegacyRepositoryRedirect("en", "view=mine&resource_type=skill")
  ).toBe("/nexent/en/resource-space?tab=agent&view=repository");
});
