// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { render, screen } from "@testing-library/react";
import { App } from "antd";
import type { ReactNode } from "react";
import JSZip from "jszip";
import { expect, test, vi } from "vitest";
import RepositorySkillDetail from "@/components/skill/RepositorySkillDetail";
import type { SkillRepositoryListingDetail } from "@/types/skillRepository";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/components/common/StandardModal", () => ({
  StandardModal: ({ children }: { children: ReactNode }) => (
    <div>{children}</div>
  ),
}));
vi.mock("@/components/common/markdownRenderer", () => ({
  MarkdownRenderer: ({ content }: { content: string }) => <div>{content}</div>,
}));
vi.mock("@/lib/logger", () => ({ default: { error: vi.fn() } }));

function show(detail: Partial<SkillRepositoryListingDetail>) {
  render(
    <App>
      <RepositorySkillDetail
        open
        detail={{
          skill_repository_id: 1,
          name: "Example",
          status: "shared",
          ...detail,
        }}
        isLoading={false}
        isError={false}
        isFetching={false}
        onClose={vi.fn()}
        onRetry={vi.fn()}
      />
    </App>
  );
}

test("reads the frozen ZIP and removes its common root folder", async () => {
  const zip = new JSZip();
  zip.file("example/SKILL.md", "Frozen skill content");
  zip.file("example/manual.pdf", new Uint8Array([0, 1, 2]));
  show({ skill_zip_base64: await zip.generateAsync({ type: "base64" }) });
  expect(await screen.findByText("Frozen skill content")).toBeVisible();
  expect(screen.getByText("manual.pdf")).toBeVisible();
  expect(screen.queryByText("example/SKILL.md")).not.toBeInTheDocument();
});

test("uses snapshot content when the archive is absent", async () => {
  show({ skill_info_json: { content: "Snapshot content" } });
  expect(await screen.findByText("Snapshot content")).toBeVisible();
});

test("reports corrupt archives while retaining the skill metadata", async () => {
  show({ skill_zip_base64: "invalid-archive" });
  expect(
    await screen.findByText("skillManagement.detail.fileReadFailed")
  ).toBeVisible();
  expect(screen.getByText("Example")).toBeVisible();
});
