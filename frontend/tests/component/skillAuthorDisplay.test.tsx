// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { fireEvent, render, screen } from "@testing-library/react";
import { App } from "antd";
import { expect, test, vi } from "vitest";
import { MineSkillCard } from "@/app/resource-space/skill/components/MineSkillsView";
import { RepositoryPresentationContext } from "@/hooks/useRepositoryPresentation";
import type { MyEditableSkillItem } from "@/types/skillRepository";

const auth = vi.hoisted(() => ({ authProvider: "password" }));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({ user: auth }),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/app/resource-space/components/ResourceReviewCenter", () => ({
  ResourceReviewLink: ({ review }: { review?: { status: string } | null }) =>
    review ? <a href="#review">{review.status}</a> : null,
}));
vi.mock(
  "@/app/resource-space/skill/components/MineApplyListingModal",
  () => ({ MineApplyListingModal: () => null })
);

test.each(["cards"] as const)(
  "aligns pending and rejected badges beside the skill name in %s",
  (layout) => {
    for (const status of ["pending_review", "rejected"] as const) {
      const { unmount } = render(
        <App>
          <RepositoryPresentationContext.Provider
            value={{ layout, resourceType: "skill" }}
          >
            <MineSkillCard
              skill={{
                skill_id: 8,
                name: "Review skill",
                permission: "EDIT",
                latest_review: { review_id: "review-8", status },
                repository_info: [],
              }}
              onEdit={vi.fn()}
              onView={vi.fn()}
              onDelete={vi.fn()}
              onApplyListing={vi.fn()}
              onViewReview={vi.fn()}
            />
          </RepositoryPresentationContext.Provider>
        </App>
      );
      expect(screen.getAllByText(status)).toHaveLength(1);
      expect(
        screen.getByRole("heading", { name: /Review skill/ })
      ).toContainElement(screen.getByText(status));
      unmount();
    }
  }
);
vi.mock(
  "@/app/resource-space/skill/components/SkillReviewStatusModal",
  () => ({ SkillReviewStatusModal: () => null })
);
vi.mock("@/app/resource-space/skill/components/CreateNewSkillCard", () => ({
  CreateNewSkillCard: () => null,
}));
vi.mock("@/components/resource/ResourceCardGrid", () => ({
  default: () => null,
}));
vi.mock("@/components/tag/TagFilterControls", () => ({ default: () => null }));
vi.mock("@/components/tag/TagFilterPopover", () => ({ default: () => null }));
vi.mock("@/app/resource-space/components/RepositoryDisplayControls", () => ({
  default: () => null,
}));

test.each([
  ["password", "author@example.test", undefined, "author@example.test"],
  ["cas", "author@example.test", "Author name", "Author name"],
  ["cas", "author@example.test", "   ", "author@example.test"],
  ["password", undefined, undefined, "skillRepository.detail.unknownAuthor"],
  ["password", "   ", undefined, "skillRepository.detail.unknownAuthor"],
])(
  "renders readable author for %s with email %s",
  (provider, email, username, expected) => {
    auth.authProvider = provider;
    const skill: MyEditableSkillItem = {
      skill_id: 1,
      name: "Helper",
      created_by: "internal-author-uuid",
      author: email,
      author_cas_username: username,
      permission: "READ_ONLY",
      repository_info: [],
    };
    render(
      <App>
        <RepositoryPresentationContext.Provider
          value={{ layout: "cards", resourceType: "skill" }}
        >
          <MineSkillCard
            skill={skill}
            onEdit={vi.fn()}
            onView={vi.fn()}
            onDelete={vi.fn()}
            onApplyListing={vi.fn()}
            onViewReview={vi.fn()}
          />
        </RepositoryPresentationContext.Provider>
      </App>
    );
    expect(screen.getByTitle(expected)).toHaveTextContent(expected);
    expect(
      screen.getByRole("heading", { name: "Helper" }).parentElement
    ).toContainElement(screen.getByTitle(expected));
    expect(screen.queryByText(/internal-author-uuid/)).not.toBeInTheDocument();
    expect(skill.created_by).toBe("internal-author-uuid");
    expect(
      screen.queryByRole("button", {
        name: "skillRepository.common.moreActions",
      })
    ).not.toBeInTheDocument();
  }
);

test.each([
  ["custom", "EDIT", "edit"],
  ["custom", "READ_ONLY", "view"],
  ["custom", "PRIVATE", "view"],
  ["official", "EDIT", "view"],
] as const)("opens the expected panel for a %s skill with %s permission", async (source, permission, target) => {
  const onEdit = vi.fn();
  const onView = vi.fn();
  render(
    <App>
      <RepositoryPresentationContext.Provider
        value={{ layout: "cards", resourceType: "skill" }}
      >
        <MineSkillCard
          skill={{
            skill_id: 12,
            name: "Personal skill",
            source,
            permission,
            repository_info: [],
          }}
          onEdit={onEdit}
          onView={onView}
          onDelete={vi.fn()}
          onApplyListing={vi.fn()}
          onViewReview={vi.fn()}
        />
      </RepositoryPresentationContext.Provider>
    </App>
  );
  fireEvent.click(screen.getByRole("button", { name: "Personal skill" }));
  expect(onEdit).toHaveBeenCalledTimes(target === "edit" ? 1 : 0);
  expect(onView).toHaveBeenCalledTimes(target === "view" ? 1 : 0);
  if (source === "official") {
    fireEvent.click(screen.getByRole("button", {
      name: "skillRepository.common.moreActions",
    }));
    expect(await screen.findByRole("menuitem", { name: "common.delete" }))
      .toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "common.edit" }))
      .not.toBeInTheDocument();
  }
});

test.each([undefined, new URLSearchParams("view=mine")])(
  "shows the listed skill badge and offers a version update",
  async (query) => {
    const submit = vi.fn();
    render(
      <App>
        <RepositoryPresentationContext.Provider
          value={{ layout: "cards", resourceType: "skill", query }}
        >
          <MineSkillCard
            skill={{
              skill_id: 5,
              name: "Listed skill",
              permission: "EDIT",
              can_publish: true,
              downloads: 2,
              repository_info: [{ skill_repository_id: 7, status: "shared" }],
              latest_review: { review_id: "review-7", status: "approved" },
            }}
            onEdit={vi.fn()}
            onView={vi.fn()}
            onDelete={vi.fn()}
            onApplyListing={submit}
            onViewReview={vi.fn()}
          />
        </RepositoryPresentationContext.Provider>
      </App>
    );
    const badge = screen.getByText("repository.status.listed");
    expect(
      screen.getByRole("heading", { name: /Listed skill/ })
    ).toContainElement(badge);
    expect(
      screen.getByText("resourceCenter.skillInstalls").parentElement
    ).not.toContainElement(badge);
    fireEvent.click(screen.getByRole("button", {
      name: "skillRepository.common.moreActions",
    }));
    fireEvent.click(await screen.findByRole("menuitem", {
      name: "repository.mine.submitVersionUpdate",
    }));
    expect(submit).toHaveBeenCalledOnce();
  }
);
