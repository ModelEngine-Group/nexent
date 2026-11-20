// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { App } from "antd";
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TrajectoryNodeDetail } from "@/app/observability/components/TrajectoryNodeDetail";
import { TrajectorySummary } from "@/app/observability/components/TrajectorySummary";
import { BodyCache } from "@/lib/trajectory";
import { recordsPage, traceNode } from "./trajectoryFixtures";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

describe("trajectory TTFT units", () => {
  it.each([
    [0, "0 ms"],
    [999.99, "999.99 ms"],
    [1000, "1 s"],
    [1628.13, "1.63 s"],
  ])("shows %s milliseconds as %s in model details", (ttft, expected) => {
    render(
      <App>
        <TrajectoryNodeDetail
          node={traceNode({ kind: "model", ttft_ms: ttft })}
          conversationId="1"
          cache={new BodyCache()}
          onParent={vi.fn()}
          onLoaded={vi.fn()}
        />
      </App>
    );
    const metric = screen.getByText("trajectory.ttft").parentElement!;
    expect(within(metric).getByText(expected)).toBeVisible();
  });

  it("applies the same threshold to TTFT percentiles while preserving duration units", () => {
    const summary = recordsPage().summary;
    summary.ttft = {
      p50_ms: 999,
      p90_ms: 1000,
      p99_ms: 1628.13,
      sample_count: 3,
    };
    render(<TrajectorySummary summary={summary} />);
    const ttft = screen.getByText("trajectory.ttft").closest("section")!;
    for (const value of ["999 ms", "1 s", "1.63 s"]) {
      expect(within(ttft).getByText(value)).toBeVisible();
    }
    const duration = screen
      .getByText("trajectory.runDuration")
      .closest("section")!;
    expect(within(duration).queryByText(/ ms$/)).not.toBeInTheDocument();
  });
});
