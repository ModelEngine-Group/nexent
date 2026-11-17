// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { render, screen } from "@testing-library/react";
import { App } from "antd";
import { expect, test, vi } from "vitest";
import { MineSkillCard } from "@/components/repository/skill/components/MineSkillsView";
import { RepositoryPresentationContext } from "@/hooks/useRepositoryPresentation";
import type { MyEditableSkillItem } from "@/types/skillRepository";

const auth = vi.hoisted(() => ({ authProvider: "password" }));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({ user: auth }),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/components/repository/ResourceReviewLink", () => ({
  default: () => null,
}));
vi.mock(
  "@/components/repository/skill/components/MineApplyListingModal",
  () => ({ MineApplyListingModal: () => null }),
);
vi.mock(
  "@/components/repository/skill/components/SkillReviewStatusModal",
  () => ({ SkillReviewStatusModal: () => null }),
);
vi.mock("@/components/repository/skill/components/CreateNewSkillCard", () => ({
  CreateNewSkillCard: () => null,
}));
vi.mock("@/components/resource/ResourceCardGrid", () => ({
  default: () => null,
}));
vi.mock("@/components/tag/TagFilterControls", () => ({ default: () => null }));
vi.mock("@/components/tag/TagFilterPopover", () => ({ default: () => null }));
vi.mock("@/components/repository/RepositoryDisplayControls", () => ({
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
      </App>,
    );
    expect(screen.getByTitle(expected)).toHaveTextContent(expected);
    expect(screen.queryByText(/internal-author-uuid/)).not.toBeInTheDocument();
    expect(skill.created_by).toBe("internal-author-uuid");
    expect(
      screen.queryByRole("button", {
        name: "skillRepository.common.moreActions",
      }),
    ).not.toBeInTheDocument();
  },
);
