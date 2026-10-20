// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SkillFileCard } from "@/app/newchat/ui/skill-file-card";

vi.mock("@/components/common/markdownRenderer", () => ({
  MarkdownRenderer: ({ content }: { content: string }) => <div>{content}</div>,
}));
vi.mock("@/app/agents/components/capability/SkillCodePreview", () => ({
  SkillCodePreview: ({ code }: { code: string }) => <pre>{code}</pre>,
}));

it("expands a generated skill preview without an inactive confirmation action", async () => {
  render(
    <SkillFileCard
      data={{
        path: "SKILL.md",
        kind: "markdown",
        content: "Meeting minutes skill",
        isStreaming: false,
      }}
    />
  );
  await userEvent.click(screen.getByRole("button", { name: /SKILL.md/ }));
  expect(screen.getByText("Meeting minutes skill")).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /确定|Confirm|common.confirm/ })
  ).not.toBeInTheDocument();
});

it.each([false, true])(
  "expands and collapses a Python preview without inactive actions (streaming=%s)",
  async (isStreaming) => {
    render(
      <SkillFileCard
        data={{
          path: "scripts/extract_invoice.py",
          kind: "code",
          language: "python",
          content: 'print("invoice")',
          isStreaming,
        }}
      />
    );
    const trigger = screen.getByRole("button", { name: /extract_invoice.py/ });
    await userEvent.click(trigger);
    expect(screen.getByText('print("invoice")')).toBeInTheDocument();
    expect(screen.getAllByRole("button")).toEqual([trigger]);
    await userEvent.click(trigger);
    expect(screen.queryByText('print("invoice")')).not.toBeInTheDocument();
  }
);
