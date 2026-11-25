// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { beforeEach, expect, test, vi } from "vitest";
import { fetchWithAuth } from "@/lib/auth";
import { authService } from "@/services/authService";

vi.mock("@/lib/auth", () => ({
  fetchWithAuth: vi.fn(),
  generateAvatarUrl: vi.fn(),
}));
vi.mock("@/services/api", () => ({
  API_ENDPOINTS: { user: { currentUserInfo: "/api/user/current_user_info" } },
}));
vi.mock("@/services/sessionService", () => ({ sessionService: {} }));

beforeEach(() => {
  vi.mocked(fetchWithAuth).mockReset();
});

test("current user API preserves identifiers for the frontend resolver", async () => {
  vi.mocked(fetchWithAuth).mockResolvedValue(
    new Response(
      JSON.stringify({
        data: {
          user: {
            user_id: "su",
            user_email: "su@example.com",
            user_role: "SU",
            roles: ["SU"],
            group_ids: [],
            tenant_id: "owned",
            permissions: ["OPS.DASHBOARD:READ"],
            accessiblePages: [
              "ops-dashboard",
              "ops-configuration",
              "/resource-manage",
            ],
          },
        },
      })
    )
  );
  const result = await authService.getCurrentUserInfo();
  expect(result?.user.accessiblePages).toEqual([
    "ops-dashboard",
    "ops-configuration",
    "/resource-manage",
  ]);
  expect(result?.user.permissions).toEqual(["ops.dashboard:read"]);
  expect(result?.user.id).toBe("su");
  expect(result?.user).not.toHaveProperty("accessibleRoutes");
});

test("failed authorization requests do not manufacture page grants", async () => {
  vi.mocked(fetchWithAuth).mockResolvedValue(
    new Response(null, { status: 401 })
  );
  expect(await authService.getCurrentUserInfo()).toBeNull();
});
