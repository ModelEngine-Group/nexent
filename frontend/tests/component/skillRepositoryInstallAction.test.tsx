// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { ReactNode } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { RepositoryView } from "@/components/repository/skill/components/RepositoryView";
import { RepositoryPresentationContext } from "@/hooks/useRepositoryPresentation";
import type { SkillRepositoryListingItem } from "@/types/skillRepository";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/components/repository/RepositoryDisplayControls", () => ({
  default: () => null,
}));
vi.mock("@/components/tag/TagFilterPopover", () => ({ default: () => null }));
vi.mock("@/components/resource/ResourceCardGrid", () => ({
  default: ({
    items,
    renderItem,
  }: {
    items: SkillRepositoryListingItem[];
    renderItem: (item: SkillRepositoryListingItem) => ReactNode;
  }) => <>{items.map(renderItem)}</>,
}));
vi.mock("@/components/repository/skill/components/SkillRepositoryCard", () => ({
  SkillRepositoryCard: ({ action }: { action: ReactNode }) => <>{action}</>,
}));
vi.mock(
  "@/components/repository/skill/components/SkillRepositoryControls",
  () => ({
    AsyncContent: ({ children }: { children: ReactNode }) => <>{children}</>,
  }),
);

const listing: SkillRepositoryListingItem = {
  skill_repository_id: 7,
  name: "Skill",
  status: "shared",
  installation_state: "not_installed",
  installed_copies: [],
};

function renderActions(
  installingRepositoryId: number | null = null,
  installationState: SkillRepositoryListingItem["installation_state"] = "not_installed",
  copies: NonNullable<SkillRepositoryListingItem["installed_copies"]> = [],
) {
  const install = vi.fn();
  const uninstall = vi.fn();
  const detail = vi.fn();
  render(
    <RepositoryPresentationContext.Provider
      value={{ layout: "cards", resourceType: "skill" }}
    >
      <RepositoryView
        searchQuery=""
        onSearchChange={vi.fn()}
        tagDefinitions={[]}
        tagPredicates={[]}
        onTagPredicatesChange={vi.fn()}
        listings={[
          {
            ...listing,
            installation_state: installationState,
            installed_copies: copies,
          },
        ]}
        isLoading={false}
        isError={false}
        isFetching={false}
        page={1}
        total={1}
        onPageChange={vi.fn()}
        pageSize={12}
        onPageSizeChange={vi.fn()}
        onRetry={vi.fn()}
        onInstall={install}
        onUninstall={uninstall}
        onDetailClick={detail}
        showAdminMenu={false}
        onTakeDown={vi.fn()}
        installingRepositoryId={installingRepositoryId}
        takingDownRepositoryId={null}
      />
    </RepositoryPresentationContext.Provider>,
  );
  return { install, uninstall, detail };
}

const copy = { skill_id: 11, name: "My Skill", can_uninstall: true };

describe("skill repository install and uninstall actions", () => {
  it("installs an unavailable skill with one button and no dropdown", () => {
    const { install, uninstall } = renderActions();
    fireEvent.click(
      screen.getByRole("button", { name: "resourceCenter.install" }),
    );
    expect(install).toHaveBeenCalledOnce();
    expect(install.mock.calls[0][0].skill_repository_id).toBe(7);
    expect(uninstall).not.toHaveBeenCalled();
    expect(
      screen.queryByRole("button", { name: "resourceCenter.actions" }),
    ).toBeNull();
  });

  it("shows only the uninstall button for the linked copy", () => {
    const { install, uninstall } = renderActions(null, "installed", [copy]);
    expect(screen.queryByText("resourceCenter.installed")).toBeNull();
    fireEvent.click(
      screen.getByRole("button", { name: "resourceCenter.uninstall" }),
    );
    expect(uninstall).toHaveBeenCalledOnce();
    expect(uninstall.mock.calls[0][1]).toEqual(copy);
    expect(install).not.toHaveBeenCalled();
  });

  it.each([{ copies: [] }, { copies: [{ ...copy, can_uninstall: false }] }])(
    "protects source skills and read-only copies from removal",
    ({ copies }) => {
      const { install, uninstall } = renderActions(null, "installed", copies);
      expect(screen.queryByText("resourceCenter.installed")).toBeNull();
      const button = screen.getByRole("button", {
        name: "resourceCenter.uninstall",
      });
      expect(button).toBeDisabled();
      fireEvent.click(button);
      expect(uninstall).not.toHaveBeenCalled();
      expect(install).not.toHaveBeenCalled();
    },
  );

  it("chooses the installed copy before confirming uninstall", async () => {
    const { uninstall } = renderActions(null, "installed", [
      copy,
      { ...copy, skill_id: 12, name: "Second copy", can_uninstall: false },
    ]);
    fireEvent.click(
      screen.getByRole("button", { name: "resourceCenter.uninstall" }),
    );
    expect(await screen.findByRole("dialog")).toBeTruthy();
    expect(uninstall).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Second copy" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "My Skill" }));
    expect(uninstall.mock.calls[0][1]).toEqual(copy);
  });

  it("cancels copy selection without uninstalling", () => {
    const { uninstall } = renderActions(null, "installed", [
      copy,
      { ...copy, skill_id: 12, name: "Second copy" },
    ]);
    fireEvent.click(
      screen.getByRole("button", { name: "resourceCenter.uninstall" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "common.close" }));
    expect(uninstall).not.toHaveBeenCalled();
  });

  it("does not guess installation state for unlinked historical skills", () => {
    const { install, uninstall } = renderActions(null, "unknown");
    const button = screen.getByRole("button", {
      name: "resourceCenter.install",
    });
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(install).not.toHaveBeenCalled();
    expect(uninstall).not.toHaveBeenCalled();
  });

  it("blocks repeated clicks while installation is pending", () => {
    const { install } = renderActions(7);
    fireEvent.click(
      screen.getByRole("button", { name: /resourceCenter\.install$/ }),
    );
    expect(install).not.toHaveBeenCalled();
  });
});
