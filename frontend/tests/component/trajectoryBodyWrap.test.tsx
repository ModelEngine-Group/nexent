// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { App } from "antd";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TrajectoryBody } from "@/app/observability/components/TrajectoryBody";
import { BodyCache } from "@/lib/trajectory";
import { trajectoryService } from "@/services/trajectoryService";
import type { ContentReference } from "@/types/trajectory";
import { body } from "./trajectoryFixtures";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/services/trajectoryService", () => ({
  trajectoryService: { content: vi.fn() },
}));
const content = vi.mocked(trajectoryService.content);
const copy = vi.fn().mockResolvedValue(undefined);
const cache = new BodyCache();
const source = JSON.stringify({
  input: "中文".repeat(100),
  url: `https://example.test/${"x".repeat(500)}`,
});
const component = (
  slot = "input",
  nodeId = "node",
  reference = body(source)
) => (
  <TrajectoryBody
    reference={reference}
    slot={slot}
    nodeId={nodeId}
    conversationId="1"
    cache={cache}
    onLoaded={vi.fn()}
  />
);

beforeEach(() => {
  content.mockReset();
  copy.mockClear();
  cache.clear();
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText: copy },
  });
});

describe("trajectory body word wrapping", () => {
  it.each([
    ["input", "json"],
    ["input", "text"],
    ["output", "json"],
    ["output", "text"],
  ])(
    "toggles wrapping for %s in %s mode without changing copied contents",
    async (slot, mode) => {
      const view = render(<App>{component(slot)}</App>);
      if (mode === "text") fireEvent.click(screen.getByText("trajectory.text"));
      const pre = view.container.querySelector("pre")!;
      const expected =
        mode === "json" ? JSON.stringify(JSON.parse(source), null, 2) : source;
      expect(pre.classList.contains("is-wrapped")).toBe(false);
      const toggle = screen.getByRole("button", {
        name: "trajectory.wrapLines",
      });
      expect(toggle).toHaveAttribute("aria-pressed", "false");
      fireEvent.click(toggle);
      expect(pre).toHaveClass("is-wrapped");
      expect(
        screen.getByRole("button", { name: "trajectory.unwrapLines" })
      ).toHaveAttribute("aria-pressed", "true");
      expect(pre.querySelector("code")?.textContent).toBe(expected);
      fireEvent.click(screen.getByRole("button", { name: "trajectory.copy" }));
      await waitFor(() => expect(copy).toHaveBeenCalledWith(expected));
      fireEvent.click(
        screen.getByRole("button", { name: "trajectory.unwrapLines" })
      );
      expect(pre).not.toHaveClass("is-wrapped");
      expect(pre.querySelector("code")?.textContent).toBe(expected);
      expect(content).not.toHaveBeenCalled();
    }
  );

  it("keeps input and output switches independent and resets them for another node", () => {
    const view = render(
      <App>
        {component("input")}
        {component("output")}
      </App>
    );
    const sections = view.container.querySelectorAll(".trajectory-body");
    fireEvent.click(
      within(sections[0] as HTMLElement).getByRole("button", {
        name: "trajectory.wrapLines",
      })
    );
    expect(sections[0].querySelector("pre")).toHaveClass("is-wrapped");
    expect(sections[1].querySelector("pre")).not.toHaveClass("is-wrapped");
    view.rerender(
      <App>
        {component("input", "another")}
        {component("output", "another")}
      </App>
    );
    expect(view.container.querySelectorAll("pre.is-wrapped")).toHaveLength(0);
  });

  it("retains wrapping through format and expansion changes", () => {
    const view = render(<App>{component()}</App>);
    fireEvent.click(
      screen.getByRole("button", { name: "trajectory.wrapLines" })
    );
    fireEvent.click(screen.getByText("trajectory.text"));
    fireEvent.click(
      screen.getByRole("button", { name: "trajectory.expandContent" })
    );
    const pre = view.container.querySelector("pre")!;
    expect(pre).toHaveClass("is-wrapped", "trajectory-body-full");
    expect(pre.querySelector("code")?.textContent).toBe(source);
    fireEvent.click(screen.getByText("JSON"));
    expect(pre).toHaveClass("is-wrapped");
    expect(pre.querySelector("code")?.textContent).toBe(
      JSON.stringify(JSON.parse(source), null, 2)
    );
  });

  it.each(["not_captured", "expired"] as const)(
    "disables wrapping for %s body",
    (availability) => {
      const reference: ContentReference = {
        ...body(""),
        availability,
        text: null,
      };
      const view = render(<App>{component("input", "node", reference)}</App>);
      expect(
        screen.getByRole("button", { name: "trajectory.wrapLines" })
      ).toBeDisabled();
      expect(view.container.querySelector("pre")).toBeNull();
    }
  );
});
