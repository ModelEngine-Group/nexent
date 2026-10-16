// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { beforeEach, describe, expect, it, vi } from "vitest";
import { listUsers, updateUser } from "@/services/userService";
import {
  addUserToGroup,
  removeUserFromGroup,
  updateGroupMembers,
} from "@/services/groupService";
import { fetchWithAuth } from "@/lib/auth";
vi.mock("@/lib/auth", () => ({ fetchWithAuth: vi.fn() }));
const request = vi.mocked(fetchWithAuth);
beforeEach(() => {
  vi.clearAllMocks();
});
describe("identity metadata is read-only across existing API contracts", () => {
  it.each(["Bob", "bob@test"])(
    "forwards the search string %s without new request fields",
    async (search) => {
      request.mockResolvedValue(
        new Response(JSON.stringify({ data: [], total: 0 }))
      );
      await listUsers("tenant", 1, 10, { search });
      expect(JSON.parse(String(request.mock.calls[0][1]?.body))).toEqual({
        tenant_id: "tenant",
        page: 1,
        page_size: 10,
        search,
        sort_by: "created_at",
        sort_order: "desc",
      });
    }
  );
  it("preserves metadata and raw emails while keeping list filters and ordering unchanged", async () => {
    const users = [
      { id: "a", username: "raw@test", cas_username: "用户名", role: "USER" },
    ];
    request.mockResolvedValue(
      new Response(
        JSON.stringify({
          data: users,
          pagination: { total: 21, total_pages: 3 },
        })
      )
    );
    const result = await listUsers("tenant", 2, 10, {
      search: " raw@test ",
      roles: ["USER"],
      groupIds: [7],
    });
    expect(result).toEqual({ users, total: 21, totalPages: 3 });
    expect(JSON.parse(String(request.mock.calls[0][1]?.body))).toEqual({
      tenant_id: "tenant",
      sort_by: "created_at",
      sort_order: "desc",
      page: 2,
      page_size: 10,
      search: "raw@test",
      roles: ["USER"],
      group_ids: [7],
    });
  });
  it("sends only original user IDs and mutation fields", async () => {
    request.mockImplementation(
      async () => new Response(JSON.stringify({ data: {}, message: "ok" }))
    );
    await updateUser("a", { role: "DEV" });
    await addUserToGroup(7, "a");
    await removeUserFromGroup(7, "b");
    await updateGroupMembers(7, ["a", "b"]);
    expect(
      request.mock.calls.map(([, options]) => [
        options?.method,
        options?.body && JSON.parse(String(options.body)),
      ])
    ).toEqual([
      ["PUT", { role: "DEV" }],
      ["POST", { user_id: "a" }],
      ["DELETE", undefined],
      ["PUT", { user_ids: ["a", "b"] }],
    ]);
    expect(request.mock.calls[0][0]).toMatch(/a$/);
    expect(request.mock.calls[2][0]).toMatch(/b$/);
  });
});
