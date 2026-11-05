// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { TooltipProvider } from "../../components/ui/tooltip";
import { ModelMigrationBadge } from "../../app/[locale]/models/components/model/ModelMigrationBadge";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

it.each([
  ["migrated" as const, true, "pending"],
  ["migrated" as const, false, "reviewed"],
  ["failed" as const, undefined, "failed"],
])(
  "shows %s review=%s as a reminder without a disabled interaction",
  (migrationStatus, migrationReviewRequired, label) => {
    render(
      <TooltipProvider>
        <ModelMigrationBadge
          model={{ migrationStatus, migrationReviewRequired }}
        />
      </TooltipProvider>
    );
    const badge = screen.getByText(`modelMigration.${label}`);
    expect(badge).toBeVisible();
    expect(badge).not.toHaveAttribute("disabled");
  }
);

it("does not mark outlets without a migration source", () => {
  const { container } = render(
    <TooltipProvider>
      <ModelMigrationBadge model={{}} />
    </TooltipProvider>
  );
  expect(container).toBeEmptyDOMElement();
});
