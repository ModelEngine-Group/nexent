// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { App, ConfigProvider } from "antd";
import JSZip from "jszip";
import { expect, test, vi } from "vitest";
import RepositorySkillDetail from "@/app/resource-space/skill/components/RepositorySkillDetail";
import { RepositoryPresentationContext } from "@/hooks/useRepositoryPresentation";
import type { SkillRepositoryListingDetail } from "@/types/skillRepository";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: { count?: number }) =>
      key === "skillRepository.detail.agentReferenceCount"
        ? `${options?.count} agents`
        : key,
  }),
}));
vi.mock("@/components/common/markdownRenderer", () => ({
  MarkdownRenderer: ({ content }: { content: string }) => <div>{content}</div>,
}));
vi.mock("@/lib/logger", () => ({ default: { error: vi.fn() } }));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({ user: { authProvider: undefined } }),
}));

function show(
  detail: Partial<SkillRepositoryListingDetail>,
  options: {
    onInstall?: () => void;
    onClose?: () => void;
    installed?: boolean;
  } = {}
) {
  render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <App>
        <RepositoryPresentationContext.Provider
          value={{ layout: "cards", resourceType: "skill" }}
        >
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
            {...options}
          />
        </RepositoryPresentationContext.Provider>
      </App>
    </ConfigProvider>
  );
  expect(document.querySelector(".ant-drawer-right")).not.toBeNull();
  expect(document.querySelector(".ant-modal")).toBeNull();
}

test.each([
  [11, "11 agents"],
  [0, "0 agents"],
  [undefined, "resourceCenter.notRecorded"],
])("displays the agent reference count %s", (count, expected) => {
  show({ agent_reference_count: count });
  const row = screen.getByText(
    "skillRepository.detail.referencedBy"
  ).parentElement!;
  expect(within(row).getByText(expected)).toBeVisible();
});

test("reads the frozen ZIP and removes its common root folder", async () => {
  const zip = new JSZip();
  zip.file("example/SKILL.md", "Frozen skill content");
  zip.file("example/manual.pdf", new Uint8Array([0, 1, 2]));
  show({ skill_zip_base64: await zip.generateAsync({ type: "base64" }) });
  expect(await screen.findByText("Frozen skill content")).toBeVisible();
  expect(screen.getByText("manual.pdf")).toBeVisible();
  expect(screen.queryByText("example/SKILL.md")).not.toBeInTheDocument();
});

test("opens the entry source with line numbers and browses the published folders", async () => {
  const zip = new JSZip();
  const source = "---\r\nversion: v1.0.0\r\n---\r\n# Example\r\n";
  zip.file("Example/reference/reference.md", "Reference text");
  zip.file("Example/SKILL.md", source);
  const onInstall = vi.fn();
  const onClose = vi.fn();
  const archive = await zip.generateAsync({ type: "base64" });
  show(
    {
      source: "official",
      skill_zip_base64: archive,
    },
    { onInstall, onClose }
  );

  expect(screen.getByText("skillRepository.detail.official")).toBeVisible();
  expect(
    await screen.findByText("skillRepository.detail.entryFile")
  ).toBeVisible();
  expect(
    screen.queryByText("resourceCenter.publishedVersion")
  ).not.toBeInTheDocument();
  expect(screen.getByText(/version: v1\.0\.0/)).toBeVisible();
  expect(screen.getByText("1 2 3 4")).toHaveAttribute("aria-hidden", "true");
  await waitFor(() => {
    expect(
      screen.getByText("reference.md").closest(".ant-tree-treenode-motion")
    ).toBeNull();
  });
  fireEvent.click(screen.getByText("reference.md"));
  expect(await screen.findByText("Reference text")).toBeVisible();
  const footer = within(screen.getByRole("contentinfo"));
  const install = footer.getByRole("button", {
    name: "resourceCenter.install",
  });
  expect(footer.getAllByRole("button")).toHaveLength(2);
  expect(install).toBeEnabled();
  fireEvent.click(install);
  expect(onInstall).toHaveBeenCalledOnce();
  fireEvent.click(footer.getByRole("button", { name: "common.close" }));
  expect(onClose).toHaveBeenCalledOnce();
});

test("uses snapshot content when the archive is absent", async () => {
  show(
    { skill_info_json: { content: "Snapshot content" } },
    { onInstall: vi.fn() }
  );
  await waitFor(() =>
    expect(screen.getByText("Snapshot content")).toBeVisible()
  );
  expect(
    screen.getByRole("button", { name: "resourceCenter.install" })
  ).toBeDisabled();
});

test("labels an installed skill and disables reinstalling it", async () => {
  const zip = new JSZip();
  zip.file("SKILL.md", "Installed skill content");
  const onInstall = vi.fn();
  show(
    { skill_zip_base64: await zip.generateAsync({ type: "base64" }) },
    { onInstall, installed: true }
  );
  expect(await screen.findByText("Installed skill content")).toBeVisible();
  const button = screen.getByRole("button", {
    name: "resourceCenter.installed",
  });
  expect(button).toBeDisabled();
  fireEvent.click(button);
  expect(onInstall).not.toHaveBeenCalled();
});

test("reports corrupt archives while retaining the skill metadata", async () => {
  show({ skill_zip_base64: "invalid-archive" });
  await waitFor(() =>
    expect(
      screen.getByText("skillManagement.detail.fileReadFailed")
    ).toBeVisible()
  );
  expect(screen.getByText("Example")).toBeVisible();
});
