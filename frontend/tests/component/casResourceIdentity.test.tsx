// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import UserList from "../../app/[locale]/resource-manage/components/resources/UserList";
import GroupList from "../../app/[locale]/resource-manage/components/resources/GroupList";
import ApiKeyList from "../../app/[locale]/resource-manage/components/resources/ApiKeyList";
const fixtures = vi.hoisted(() => ({
  provider: "cas",
  userList: vi.fn(),
  confirm: vi.fn(),
  updateUser: vi.fn(),
  updateGroup: vi.fn(),
  updateMembers: vi.fn(),
  refetch: vi.fn(),
  users: [
    {
      id: "a",
      username: "a@test",
      cas_username: "同名用户",
      role: "USER",
      group_names: [],
    },
    {
      id: "b",
      username: "b@test",
      cas_username: "同名用户",
      role: "USER",
      group_names: [],
    },
  ],
}));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({
    user: { authProvider: fixtures.provider },
  }),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, values?: { name?: string }) =>
      values?.name ? `${key}:${values.name}` : key,
  }),
}));
vi.mock("@/hooks/user/useUserList", () => ({
  useUserList: (...args: unknown[]) => {
    fixtures.userList(...args);
    return {
      data: { users: fixtures.users, total: 2 },
      isLoading: false,
      refetch: fixtures.refetch,
    };
  },
}));
vi.mock("@/hooks/group/useGroupList", () => ({
  useGroupList: () => ({
    data: {
      groups: [
        {
          group_id: 7,
          group_name: "Team",
          group_description: "Description",
          user_count: 1,
        },
      ],
      total: 1,
    },
    isLoading: false,
    refetch: fixtures.refetch,
  }),
}));
vi.mock("@/hooks/user/useApiKeyList", () => ({
  useApiKeyList: () => ({
    data: {
      items: [
        {
          token_id: 1,
          user_id: "a",
          access_key: "test-key",
          owner_email: "a@test",
          owner_cas_username: "owner",
          creator_email: "b@test",
          creator_cas_username: "creator",
          total_usage_count: 0,
        },
      ],
      total: 1,
    },
    isLoading: false,
    refetch: fixtures.refetch,
  }),
}));
vi.mock("@/services/apiKeyService", () => ({
  refreshTenantApiKey: vi.fn(),
  revokeTenantApiKeys: vi.fn(),
}));
vi.mock("@/hooks/useConfirmModal", () => ({
  useConfirmModal: () => ({ confirm: fixtures.confirm }),
}));
vi.mock("@/services/userService", () => ({
  updateUser: fixtures.updateUser,
  deleteUser: vi.fn(),
}));
vi.mock("@/services/groupService", () => ({
  createGroup: vi.fn(),
  updateGroup: fixtures.updateGroup,
  deleteGroup: vi.fn(),
  addUserToGroup: vi.fn(),
  removeUserFromGroup: vi.fn(),
  getGroupMembers: vi.fn(async () => [fixtures.users[0]]),
  updateGroupMembers: fixtures.updateMembers,
}));
beforeEach(() => {
  fixtures.provider = "cas";
  vi.clearAllMocks();
});
function groupView() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <GroupList tenantId="tenant" />
    </QueryClientProvider>
  );
}
describe("resource identity operations", () => {
  it("shows names in user rows, edit and confirmation but saves original user ID and role", async () => {
    render(<UserList tenantId="tenant" />);
    expect(
      screen.getByRole("columnheader", { name: "common.username" })
    ).toBeInTheDocument();
    expect(screen.getAllByText("同名用户")).toHaveLength(2);
    const row = screen.getAllByRole("row")[1];
    fireEvent.click(within(row).getAllByRole("button")[0]);
    expect(await screen.findByDisplayValue("同名用户")).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "common.confirm" }));
    await waitFor(() =>
      expect(fixtures.updateUser).toHaveBeenCalledWith("a", { role: "USER" })
    );
    fireEvent.click(within(row).getAllByRole("button")[1]);
    expect(fixtures.confirm.mock.calls[0][0].title).toContain("同名用户");
    const search = screen.getByPlaceholderText(
      "tenantResources.users.searchPlaceholder"
    );
    fireEvent.change(search, { target: { value: "a@test" } });
    expect(fixtures.userList).toHaveBeenLastCalledWith("tenant", 1, 10, {
      search: "a@test",
      roles: [],
      groupIds: [],
    });
  });
  it("retains local email display", () => {
    fixtures.provider = "local";
    render(<UserList tenantId="tenant" />);
    expect(
      screen.getByRole("columnheader", { name: "common.email" })
    ).toBeInTheDocument();
    expect(screen.getByText("a@test")).toBeInTheDocument();
    expect(screen.queryByText("同名用户")).not.toBeInTheDocument();
  });
  it.each(["cas", "local"])(
    "matches API-key owner and creator headers to the %s viewer",
    (provider) => {
      fixtures.provider = provider;
      render(<ApiKeyList tenantId="tenant" />);
      const suffix = provider === "cas" ? "Username" : "Email";
      for (const role of ["owner", "creator"]) {
        expect(
          screen.getByRole("columnheader", {
            name: `tenantResources.apiKeys.${role}${suffix}`,
          })
        ).toBeInTheDocument();
      }
      expect(
        screen.getByText(provider === "cas" ? "owner" : "a@test")
      ).toBeInTheDocument();
      expect(
        screen.getByText(provider === "cas" ? "creator" : "b@test")
      ).toBeInTheDocument();
    }
  );
  it("renders CAS member options while preserving IDs and email filtering", async () => {
    groupView();
    fireEvent.click(
      within(screen.getAllByRole("row")[1]).getAllByRole("button")[1]
    );
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText("同名用户")).toBeInTheDocument();
    const selector = within(dialog).getByRole("combobox");
    fireEvent.mouseDown(selector);
    fireEvent.change(selector, { target: { value: "b@test" } });
    const options = await screen.findAllByText("同名用户");
    fireEvent.click(options[options.length - 1]);
    fireEvent.click(
      within(dialog).getByRole("button", { name: "common.confirm" })
    );
    await waitFor(() =>
      expect(fixtures.updateMembers).toHaveBeenCalledWith(7, ["a", "b"])
    );
    expect(fixtures.updateGroup).toHaveBeenCalledWith(7, {
      group_name: "Team",
      group_description: "Description",
    });
  });
});
