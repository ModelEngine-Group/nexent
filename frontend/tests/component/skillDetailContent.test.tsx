// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Skill } from "@/types/agentConfig";
import type { SkillFileContent } from "@/types/skill";
import SkillDetailModal from "@/app/agents/components/capability/SkillDetailModal";

const api = vi.hoisted(() => ({
  fetchSkillById: vi.fn(),
  fetchSkillFiles: vi.fn(),
  fetchSkillFileContent: vi.fn(),
}));

vi.mock("@/services/agentConfigService", () => ({
  ...api,
  SkillFilesAccessDeniedError: class extends Error {},
}));
vi.mock("react-i18next", () => {
  const t = (key: string) => key;
  return { useTranslation: () => ({ t }) };
});
vi.mock("@/lib/logger", () => ({ default: { error: vi.fn() } }));
vi.mock("@/app/agents/components/capability/SkillDraftPanel", () => ({
  default: ({ skillTabs }: { skillTabs: SkillFileContent[] }) => (
    <div data-testid="skill-tabs">
      {skillTabs.map((tab) => (
        <pre key={tab.path}>{tab.content}</pre>
      ))}
    </div>
  ),
}));

const summary: Skill = {
  skill_id: 7,
  name: "metadata-only",
  description: "List metadata",
  source: "custom",
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

beforeEach(() => {
  vi.resetAllMocks();
  api.fetchSkillById.mockResolvedValue({
    success: true,
    data: { ...summary, content: "full detail body" },
  });
  api.fetchSkillFiles.mockResolvedValue([{ name: "SKILL.md", type: "file" }]);
  api.fetchSkillFileContent.mockResolvedValue({
    status: "readable",
    content: "canonical file body",
    encoding: "utf-8",
  });
});

describe("Skill detail without list content", () => {
  it("loads full files on demand when the list supplies metadata only", async () => {
    render(<SkillDetailModal skill={summary} open onClose={vi.fn()} />);
    expect(await screen.findByText("canonical file body")).toBeInTheDocument();
    expect(api.fetchSkillById).toHaveBeenCalledWith(7, undefined);
    expect(api.fetchSkillFileContent).toHaveBeenCalledWith(
      "metadata-only",
      "SKILL.md"
    );
  });

  it("keeps the fetched detail body if file enumeration fails", async () => {
    api.fetchSkillFiles.mockRejectedValue(new Error("file tree unavailable"));
    render(<SkillDetailModal skill={summary} open onClose={vi.fn()} />);
    expect(await screen.findByText("full detail body")).toBeInTheDocument();
    expect(
      await screen.findByText("skillManagement.detail.noFiles")
    ).toBeInTheDocument();
  });

  it("keeps the fetched detail body if the file tree is empty", async () => {
    api.fetchSkillFiles.mockResolvedValue([]);
    render(<SkillDetailModal skill={summary} open onClose={vi.fn()} />);
    expect(await screen.findByText("full detail body")).toBeInTheDocument();
  });

  it("can still load files when the metadata detail request fails", async () => {
    api.fetchSkillById.mockResolvedValue({ success: false, data: null });
    render(<SkillDetailModal skill={summary} open onClose={vi.fn()} />);
    expect(await screen.findByText("canonical file body")).toBeInTheDocument();
  });

  it("shows the existing error feedback when neither detail nor files load", async () => {
    api.fetchSkillById.mockResolvedValue({ success: false, data: null });
    api.fetchSkillFiles.mockRejectedValue(new Error("unavailable"));
    render(<SkillDetailModal skill={summary} open onClose={vi.fn()} />);
    expect(
      await screen.findByText("skillManagement.detail.noFiles")
    ).toBeInTheDocument();
    expect(screen.getByTestId("skill-tabs")).toHaveTextContent("");
  });

  it("does not replace a different skill with a late detail response", async () => {
    const oldDetail = deferred<{
      success: boolean;
      data: Skill & { content: string };
    }>();
    api.fetchSkillById.mockReturnValueOnce(oldDetail.promise);
    api.fetchSkillFiles.mockRejectedValue(new Error("unavailable"));
    const { rerender } = render(
      <SkillDetailModal skill={summary} open onClose={vi.fn()} />
    );
    await waitFor(() => expect(api.fetchSkillById).toHaveBeenCalledTimes(1));
    const next = { ...summary, skill_id: 8, name: "next" };
    api.fetchSkillById.mockResolvedValueOnce({
      success: true,
      data: { ...next, content: "next detail body" },
    });
    rerender(<SkillDetailModal skill={next} open onClose={vi.fn()} />);
    expect(await screen.findByText("next detail body")).toBeInTheDocument();
    await act(async () => {
      oldDetail.resolve({
        success: true,
        data: { ...summary, content: "stale body" },
      });
    });
    expect(screen.queryByText("stale body")).not.toBeInTheDocument();
    expect(screen.getByText("next detail body")).toBeInTheDocument();
  });
});
