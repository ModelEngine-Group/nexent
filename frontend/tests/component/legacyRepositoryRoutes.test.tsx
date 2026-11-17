// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { render } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import LegacyRepositoryEntry from "@/components/repository/LegacyRepositoryEntry";
import { buildLegacyRepositoryRedirect } from "@/lib/legacyRepositoryRoutes";

vi.mock("@/base-path.mjs", () => ({ BASE_PATH: "/nexent" }));
const navigation = vi.hoisted(() => ({ replace: vi.fn(), search: "" }));
vi.mock("next/navigation", () => ({
  useParams: () => ({ locale: "zh" }),
  useRouter: () => ({ replace: navigation.replace }),
  useSearchParams: () => new URLSearchParams(navigation.search),
}));
vi.mock("next/dynamic", () => ({
  default: () => () => <div>personal agents</div>,
}));

beforeEach(() => {
  navigation.replace.mockReset();
  navigation.search = "";
});

test.each(["agent", "mcp", "skill"] as const)(
  "redirects the retired %s landing page",
  (type) => {
    render(<LegacyRepositoryEntry resourceType={type} />);
    expect(navigation.replace).toHaveBeenCalledWith(
      `/nexent/zh/resource-space?tab=${type}&view=repository`
    );
  }
);

test.each(["agent", "mcp", "skill"] as const)(
  "routes %s reviews to the unified review center",
  (type) => {
    const href = buildLegacyRepositoryRedirect(
      "en",
      type,
      "tab=review&review_id=42"
    );
    expect(href).toBe(
      `/nexent/en/resource-space?tab=review&review_id=42&resource_type=${type}`
    );
  }
);

test.each(["mcp", "skill"] as const)(
  "preserves personal %s filters and detail IDs",
  (type) => {
    const href = buildLegacyRepositoryRedirect(
      "zh",
      type,
      "tab=mine&page=2&skill_id=42&keyword=a%26b"
    );
    const params = new URL(href!, "http://localhost").searchParams;
    expect(params.get("tab")).toBe(type);
    expect(params.get("view")).toBe("mine");
    expect(params.get("skill_id")).toBe("42");
    expect(params.get("keyword")).toBe("a&b");
    expect(params.get("page")).toBe("2");
  }
);

test("keeps published-agent usage guide links working without the old tab shell", () => {
  navigation.search = "tab=mine&agent_id=42&onboarding=usage-menu";
  const { getByText } = render(<LegacyRepositoryEntry resourceType="agent" />);
  expect(getByText("personal agents")).toBeTruthy();
  expect(navigation.replace).not.toHaveBeenCalled();
});

test("does not allow stale view and resource type to override the destination", () => {
  expect(
    buildLegacyRepositoryRedirect("en", "mcp", "view=mine&resource_type=skill")
  ).toBe("/nexent/en/resource-space?tab=mcp&view=repository");
});
