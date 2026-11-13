// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useState } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import { expect, test, vi } from "vitest";
import SkillCreationFiles from "@/components/skill/SkillCreationFiles";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/components/common/markdownRenderer", () => ({
  MarkdownRenderer: ({ content }: { content: string }) => <div>{content}</div>,
}));

function Editor() {
  const [files, setFiles] = useState([
    { path: "SKILL.md", content: "Initial body" },
  ]);
  return (
    <App>
      <SkillCreationFiles files={files} onChange={setFiles} disabled={false} />
    </App>
  );
}

test("edits the draft and previews the saved text without submitting to a server", () => {
  render(<Editor />);
  expect(screen.getByText("Initial body")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "common.edit" }));
  fireEvent.change(
    screen.getByRole("textbox", { name: "skillCreation.fileContent" }),
    { target: { value: "Changed body" } }
  );
  fireEvent.click(screen.getByRole("button", { name: "common.save" }));
  expect(screen.getByText("Changed body")).toBeVisible();
});

test("rejects traversal paths and adds a valid nested file", async () => {
  render(<Editor />);
  fireEvent.click(
    screen.getByRole("button", { name: "skillCreation.newFile" })
  );
  fireEvent.change(
    screen.getByRole("textbox", { name: "skillCreation.filePath" }),
    { target: { value: "../escape.txt" } }
  );
  fireEvent.click(screen.getByRole("button", { name: "common.confirm" }));
  await waitFor(() =>
    expect(screen.getByText("skillCreation.invalidPath")).toBeVisible()
  );
  fireEvent.change(
    screen.getByRole("textbox", { name: "skillCreation.filePath" }),
    { target: { value: "scripts/helper.txt" } }
  );
  fireEvent.click(screen.getByRole("button", { name: "common.confirm" }));
  expect(
    await screen.findByRole("textbox", { name: "skillCreation.fileContent" })
  ).toHaveValue("");
  expect(screen.getByTitle("scripts/helper.txt")).toBeVisible();
});

test("opens the file selected from the workbench conversation", () => {
  render(
    <App>
      <SkillCreationFiles
        files={[
          { path: "SKILL.md", content: "Main instructions" },
          { path: "references/guide.txt", content: "Selected reference" },
        ]}
        onChange={vi.fn()}
        disabled={false}
        selectedPath="references/guide.txt"
      />
    </App>
  );
  expect(screen.getByText("Selected reference")).toBeVisible();
  expect(screen.queryByText("Main instructions")).not.toBeInTheDocument();
});
