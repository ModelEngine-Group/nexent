// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Button, Form } from "antd";
import { describe, expect, it, vi } from "vitest";
import { UserIdentity } from "@/components/auth/UserIdentity";
import { UserIdentityInput } from "@/components/auth/UserIdentityInput";
import { getUserDisplayName } from "@/lib/userIdentity";
const session = vi.hoisted(() => ({ provider: "cas" }));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({ user: { authProvider: session.provider } }),
}));
describe("CAS presentation values", () => {
  it.each([
    ["cas", " 用户 ", "mail@test", "用户"],
    ["local", "用户", "mail@test", "mail@test"],
    [undefined, "用户", "mail@test", "mail@test"],
    ["cas", undefined, "mail@test", "mail@test"],
    ["cas", " \t", "mail@test", "mail@test"],
    ["cas", "", "—", "—"],
    ["local", "用户", " 原值 ", " 原值 "],
  ])(
    "preserves the fallback for %s/%s",
    (provider, name, fallback, expected) => {
      expect(getUserDisplayName(provider, name, fallback)).toBe(expected);
    }
  );
  it("responds to viewer changes without rewriting the record", () => {
    session.provider = "cas";
    const { rerender } = render(
      <UserIdentity casUsername="用户名" fallback="raw@test" />
    );
    expect(screen.getByText("用户名")).toBeInTheDocument();
    session.provider = "local";
    rerender(<UserIdentity casUsername="用户名" fallback="raw@test" />);
    expect(screen.getByText("raw@test")).toBeInTheDocument();
  });
  it("keeps the original form value on save while displaying the CAS name", async () => {
    session.provider = "cas";
    const save = vi.fn();
    render(
      <Form initialValues={{ username: "raw@test" }} onFinish={save}>
        <Form.Item name="username">
          <UserIdentityInput disabled casUsername="用户名" />
        </Form.Item>
        <Button htmlType="submit">Save</Button>
      </Form>
    );
    expect(screen.getByRole("textbox")).toHaveValue("用户名");
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(save).toHaveBeenCalledWith({ username: "raw@test" })
    );
  });
});
