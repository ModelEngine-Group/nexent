// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { ReactNode } from "react";
import { Button } from "antd";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SkillRepositoryCard } from "@/components/repository/skill/components/SkillRepositoryCard";
import { RepositoryPresentationContext } from "@/hooks/useRepositoryPresentation";
import type { SkillRepositoryListingStatus } from "@/types/skillRepository";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/hooks/auth/useUserDisplayName", () => ({
  useUserDisplayName: () => (_name: string, fallback: string) => fallback,
}));
vi.mock("@/components/repository/ResourcePublishedAt", () => ({
  default: () => null,
}));
vi.mock("@/components/repository/skill/components/SkillTypeIcon", () => ({
  default: () => null,
}));
vi.mock("@/components/resource/ResourceCard", () => ({
  default: ({
    actions,
    footer,
  }: {
    actions?: ReactNode;
    footer?: ReactNode;
  }) => (
    <div>
      <div data-testid="old-actions">{actions}</div>
      <div data-testid="primary-actions">{footer}</div>
    </div>
  ),
}));

function show({
  admin = true,
  installed = false,
  pending = false,
  canTakeDown,
  status = "shared",
}: {
  admin?: boolean;
  installed?: boolean;
  pending?: boolean;
  canTakeDown?: boolean;
  status?: SkillRepositoryListingStatus;
} = {}) {
  const install = vi.fn();
  const takeDown = vi.fn();
  render(
    <RepositoryPresentationContext.Provider
      value={{ layout: "cards", resourceType: "skill" }}
    >
      <SkillRepositoryCard
        listing={{
          skill_repository_id: 7,
          name: "Skill",
          status,
          can_take_down: canTakeDown,
        }}
        action={
          <Button disabled={installed} onClick={install}>
            {installed ? "Uninstall" : "Install"}
          </Button>
        }
        showAdminMenu={admin}
        isTakingDown={pending}
        onTakeDown={takeDown}
      />
    </RepositoryPresentationContext.Provider>,
  );
  return { install, takeDown };
}

describe("skill repository take-down dropdown", () => {
  it.each([false, true])(
    "moves take-down beside the primary button even when it is disabled: %s",
    async (installed) => {
      const { install, takeDown } = show({ installed });
      expect(screen.getByTestId("old-actions")).toBeEmptyDOMElement();
      const arrow = within(screen.getByTestId("primary-actions")).getByRole(
        "button",
        { name: "skillRepository.common.moreActions" },
      );
      expect(arrow).toBeEnabled();
      fireEvent.click(arrow);
      const item = await screen.findByRole("menuitem", {
        name: "skillRepository.action.status.notShared",
      });
      expect(item.className).toContain("ant-dropdown-menu-item-danger");
      expect(install).not.toHaveBeenCalled();
      expect(takeDown).not.toHaveBeenCalled();
      fireEvent.click(item);
      expect(takeDown).toHaveBeenCalledOnce();
      expect(install).not.toHaveBeenCalled();
    },
  );

  it("keeps the primary install action separate from take-down", () => {
    const { install, takeDown } = show();
    fireEvent.click(screen.getByRole("button", { name: "Install" }));
    expect(install).toHaveBeenCalledOnce();
    expect(takeDown).not.toHaveBeenCalled();
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("does not expose take-down to users without permission", () => {
    show({ admin: false });
    expect(
      screen.queryByRole("button", {
        name: "skillRepository.common.moreActions",
      }),
    ).toBeNull();
  });

  it("blocks repeated take-down requests while the operation is pending", () => {
    const { takeDown } = show({ pending: true });
    const arrow = screen.getByRole("button", {
      name: "skillRepository.common.moreActions",
    });
    expect(arrow).toBeDisabled();
    fireEvent.click(arrow);
    expect(screen.queryByRole("menu")).toBeNull();
    expect(takeDown).not.toHaveBeenCalled();
  });

  it("allows a developer with server permission to take down their listing", async () => {
    const { takeDown } = show({ admin: false, canTakeDown: true });
    fireEvent.click(
      screen.getByRole("button", {
        name: "skillRepository.common.moreActions",
      }),
    );
    fireEvent.click(
      await screen.findByRole("menuitem", {
        name: "skillRepository.action.status.notShared",
      }),
    );
    expect(takeDown).toHaveBeenCalledOnce();
  });

  it.each([
    { admin: false, canTakeDown: false },
    { admin: true, canTakeDown: false },
    { canTakeDown: true, status: "not_shared" as const },
    { canTakeDown: true, status: "pending_review" as const },
    { canTakeDown: true, status: "rejected" as const },
  ])(
    "hides take-down when permission or listing state disallows it: %j",
    (options) => {
      show(options);
      expect(
        screen.queryByRole("button", {
          name: "skillRepository.common.moreActions",
        }),
      ).toBeNull();
    },
  );
});
