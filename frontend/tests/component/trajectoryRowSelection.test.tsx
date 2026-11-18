// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { TrajectoryTimeline } from "@/app/observability/components/TrajectoryTimeline";
import { BodyCache } from "@/lib/trajectory";
import { traceNode } from "./trajectoryFixtures";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

function setup() {
  const root = traceNode();
  const child = traceNode({
    id: "model",
    parent_id: root.id,
    name: "DeepSeek",
    kind: "model",
  });
  const onSelect = vi.fn();
  render(
    <TrajectoryTimeline
      nodes={[root, child]}
      complete
      cache={new BodyCache()}
      onSelect={onSelect}
    />
  );
  const item = screen.getByRole("treeitem", { name: /Root Agent/ });
  const row = item.closest(".trajectory-timeline-row")!;
  return { root, onSelect, item, row };
}

describe("trajectory row selection", () => {
  it.each([
    ["label whitespace", ".trajectory-tree-label"],
    ["child count", "small"],
    ["duration", ".trajectory-row-duration"],
    ["name", ".trajectory-node-name"],
    ["time cell", ".trajectory-time-cell"],
    ["row gap", null],
  ])("selects the original node exactly once from %s", (_, selector) => {
    const { root, onSelect, row } = setup();
    fireEvent.click(selector ? row.querySelector(selector)! : row);
    expect(onSelect).toHaveBeenCalledOnce();
    expect(onSelect.mock.calls[0][0]).toBe(root);
  });

  it("expands and collapses without changing the selected node", () => {
    const { onSelect, row } = setup();
    fireEvent.click(row.querySelector(".trajectory-toggle")!);
    expect(
      screen.queryByRole("treeitem", { name: /DeepSeek/ })
    ).not.toBeInTheDocument();
    expect(onSelect).not.toHaveBeenCalled();
    fireEvent.click(row.querySelector(".trajectory-toggle")!);
    expect(screen.getByRole("treeitem", { name: /DeepSeek/ })).toBeVisible();
    expect(onSelect).not.toHaveBeenCalled();
  });

  it.each(["{Enter}", " "])(
    "preserves keyboard selection with %s",
    async (key) => {
      const { root, onSelect, item } = setup();
      item.focus();
      await userEvent.keyboard(key);
      expect(onSelect).toHaveBeenCalledOnce();
      expect(onSelect.mock.calls[0][0]).toBe(root);
    }
  );
});
