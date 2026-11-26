// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { McpToolGroup } from "@/components/resource-picker/McpToolGroup";
import type { Tool } from "@/types/agentConfig";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

test("agent MCP service keeps partial tool selection separate from lazy disclosure", () => {
  const tools = [
    { id: "1", name: "first" },
    { id: "2", name: "second" },
  ] as Tool[];
  const select = vi.fn();
  const renderTool = vi.fn((tool: Tool) => (
    <div key={tool.id}>{tool.name}</div>
  ));
  render(
    <McpToolGroup
      name="Agent service"
      tools={tools}
      selectedIds={new Set([1])}
      eligibleIds={new Set([1, 2])}
      selecting={false}
      searching={false}
      onSelect={select}
      renderTool={renderTool}
    />
  );
  expect(renderTool).not.toHaveBeenCalled();
  const checkbox = screen.getByRole("checkbox", {
    name: "toolPool.mcpSelectService",
  });
  expect(checkbox).toHaveAttribute("aria-checked", "mixed");
  const expand = screen.getByRole("button", { name: "Agent service" });
  fireEvent.click(expand);
  expect(expand).toHaveAttribute("aria-expanded", "true");
  expect(screen.getByText("first")).toBeVisible();
  expect(select).not.toHaveBeenCalled();
  fireEvent.click(checkbox);
  expect(select).toHaveBeenCalledWith(tools, true);
  fireEvent.click(expand);
  expect(screen.queryByText("first")).not.toBeInTheDocument();
});
