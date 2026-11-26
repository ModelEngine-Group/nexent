// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { expect, it, vi } from "vitest";
import { ComposerAttachments } from "@/app/newchat/ui/attachment";

const fixture = vi.hoisted(() => ({ remove: vi.fn() }));

vi.mock("@assistant-ui/react", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@assistant-ui/react")>()),
  AttachmentPrimitive: {
    Remove: (props: ComponentProps<"button">) => (
      <button {...props} onClick={fixture.remove} />
    ),
  },
  ComposerPrimitive: {
    Attachments: ({
      children,
    }: {
      children: (value: {
        attachment: { name: string; type: string; file?: File; size?: number };
      }) => React.ReactNode;
    }) => (
      <>
        {children({
          attachment: {
            name: "table.csv",
            type: "file",
            file: new File(["x".repeat(2048)], "table.csv"),
          },
        })}
        {children({
          attachment: { name: "archive.zip", type: "file", size: 1024 },
        })}
      </>
    ),
  },
}));

it("renders typed draft attachment cards with size and a separate remove button", async () => {
  const { container } = render(<ComposerAttachments />);
  expect(screen.getByText("table.csv")).toBeVisible();
  expect(screen.getByText("2.0 KB")).toBeVisible();
  expect(screen.getByText("archive.zip")).toBeVisible();
  expect(screen.getByText("1.0 KB")).toBeVisible();
  expect(container.querySelector(".lucide-file-spreadsheet")).not.toBeNull();
  expect(container.querySelector(".lucide-archive")).not.toBeNull();
  await userEvent.click(screen.getAllByRole("button")[0]);
  expect(fixture.remove).toHaveBeenCalledOnce();
});
