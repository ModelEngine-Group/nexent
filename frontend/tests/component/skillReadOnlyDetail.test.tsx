// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import { expect, test, vi } from "vitest";
import SkillReadOnlyDetail from "@/components/skill/SkillReadOnlyDetail";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/components/common/markdownRenderer", () => ({
  MarkdownRenderer: ({ content }: { content: string }) => <div>{content}</div>,
}));
const files = [
  { path: "SKILL.md", content: "Markdown body" },
  { path: "helper.txt", content: "Helper body" },
  { path: "manual.pdf", content: "", status: "unsupported" as const },
];
const show = () =>
  render(
    <App>
      <SkillReadOnlyDetail
        name="Example"
        source="Custom"
        description="Description"
        tags={["example"]}
        files={files}
      />
    </App>
  );

test("defaults to SKILL.md, switches files, and blocks unsupported actions", async () => {
  show();
  expect(await screen.findByText("Markdown body")).toBeVisible();
  fireEvent.click(screen.getByText("helper.txt"));
  expect(screen.getByText("Helper body")).toBeVisible();
  fireEvent.click(screen.getByText("manual.pdf"));
  expect(
    screen.getByText("skillManagement.detail.filePreviewUnsupported")
  ).toBeVisible();
  expect(screen.getByRole("button", { name: "common.copy" })).toBeDisabled();
  expect(
    screen.getByRole("button", { name: "skillRepository.detail.downloadFile" })
  ).toBeDisabled();
});

test("search filters the tree without replacing the active preview", async () => {
  show();
  fireEvent.change(
    screen.getByRole("textbox", { name: "skillManagement.detail.files" }),
    { target: { value: "missing" } }
  );
  expect(screen.getByText("skillManagement.detail.noFiles")).toBeVisible();
  expect(screen.getByText("Markdown body")).toBeVisible();
});

test("copies the active content and reports clipboard errors", async () => {
  show();
  fireEvent.click(screen.getByRole("button", { name: "common.copy" }));
  await waitFor(() =>
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith("Markdown body")
  );
  vi.mocked(navigator.clipboard.writeText).mockRejectedValueOnce(
    new Error("Denied")
  );
  fireEvent.click(screen.getByRole("button", { name: "common.copy" }));
  expect(await screen.findByText("agentUsageGuide.copyFailed")).toBeVisible();
});

test("downloads the selected readable file using its basename", async () => {
  const create = URL.createObjectURL;
  const revoke = URL.revokeObjectURL;
  URL.createObjectURL = vi.fn(() => "blob:skill-test");
  URL.revokeObjectURL = vi.fn();
  const click = vi
    .spyOn(HTMLAnchorElement.prototype, "click")
    .mockImplementation(() => {});
  try {
    show();
    fireEvent.click(
      screen.getByRole("button", {
        name: "skillRepository.detail.downloadFile",
      })
    );
    expect(URL.createObjectURL).toHaveBeenCalledWith(expect.any(Blob));
    expect(click).toHaveBeenCalledTimes(1);
    expect(click.mock.instances[0].download).toBe("SKILL.md");
    await waitFor(() =>
      expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:skill-test")
    );
  } finally {
    click.mockRestore();
    URL.createObjectURL = create;
    URL.revokeObjectURL = revoke;
  }
});
