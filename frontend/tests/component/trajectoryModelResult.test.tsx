// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { App } from "antd";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { TrajectoryNodeDetail } from "@/app/observability/components/TrajectoryNodeDetail";
import { BodyCache } from "@/lib/trajectory";
import { trajectoryService } from "@/services/trajectoryService";
import type { TrajectoryNode } from "@/types/trajectory";
import { body, traceNode } from "./trajectoryFixtures";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: { defaultValue?: string }) =>
      options?.defaultValue ?? key,
  }),
}));
vi.mock("@/services/trajectoryService", () => ({
  trajectoryService: { content: vi.fn() },
}));

const content = vi.mocked(trajectoryService.content);
const markdown =
  "### Inventory\n\n| Item | Count |\n| --- | --- |\n| Pen | 2 |";

function renderNode(overrides: Partial<TrajectoryNode>) {
  render(
    <App>
      <TrajectoryNodeDetail
        node={traceNode({ kind: "model", ...overrides })}
        conversationId="1"
        cache={new BodyCache()}
        onParent={vi.fn()}
        onLoaded={vi.fn()}
      />
    </App>
  );
}

function section(slot: "input" | "output" | "reasoning") {
  return screen
    .getByRole("button", { name: `trajectory.${slot}` })
    .closest("section")!;
}

beforeEach(() => content.mockReset());

it("shows response fields and nested provider choices and copies the original response", async () => {
  const user = userEvent.setup();
  const response = {
    model: "model-a",
    choices: [
      {
        index: 0,
        message: { role: "assistant", content: markdown },
        finish_reason: "stop",
      },
      { index: 1, delta: { content: "**Second answer**" } },
    ],
    usage: { total_tokens: 12 },
  };
  const text = JSON.stringify(response);
  renderNode({ output: body(text) });
  const output = section("output");
  const table = within(output).getByRole("table", {
    name: "trajectory.output",
  });
  const choices = within(table).getByRole("table", { name: "choices" });

  expect(table.closest(".ant-table-wrapper")?.parentElement).toBe(output);
  expect(within(table).getByRole("rowheader", { name: "usage" })).toBeVisible();
  expect(table).toHaveTextContent('{"total_tokens":12}');
  expect(
    within(choices).getByRole("rowheader", { name: "1. finish_reason" })
  ).toBeVisible();
  expect(
    within(choices).getByRole("heading", { name: "Inventory" })
  ).toBeVisible();
  expect(within(choices).getByRole("table")).toHaveTextContent("Pen");
  expect(within(choices).getByText("Second answer").tagName).toBe("STRONG");

  await user.click(
    within(output).getByRole("button", { name: "trajectory.copy" })
  );
  expect(await navigator.clipboard.readText()).toBe(text);
  const modes = within(within(output).getByRole("radiogroup"));
  expect(modes.queryByText("Markdown")).toBeNull();
  await user.click(modes.getByText("JSON"));
  expect(output.querySelector("pre code")?.textContent).toBe(
    JSON.stringify(response, null, 2)
  );
  await user.click(modes.getByText("trajectory.text"));
  expect(output.querySelector("pre code")?.textContent).toBe(text);
  await user.click(modes.getByText("trajectory.table"));
  expect(
    within(output).getByRole("table", { name: "trajectory.output" })
  ).toBeVisible();
});

it("renders merged output only after its final chunk is loaded", async () => {
  const text = JSON.stringify({ choices: [{ delta: { content: markdown } }] });
  const first = text.slice(0, 32);
  content
    .mockResolvedValueOnce({
      text: first,
      offset: 0,
      next_offset: first.length,
      complete: false,
      offset_unit: "utf8_bytes",
      byte_count: text.length,
      char_count: text.length,
    })
    .mockResolvedValueOnce({
      text: text.slice(first.length),
      offset: first.length,
      next_offset: text.length,
      complete: true,
      offset_unit: "utf8_bytes",
      byte_count: text.length,
      char_count: text.length,
    });
  renderNode({ output: body(first, false) });
  const output = section("output");
  const source = await within(output).findByText(
    (_, element) =>
      element?.tagName === "CODE" && !!element.textContent?.includes("content")
  );
  expect(
    within(output).queryByRole("radio", { name: "trajectory.table" })
  ).toBeNull();
  fireEvent.wheel(source.closest("pre")!, { deltaY: 1 });
  const table = await within(output).findByRole("table", {
    name: "trajectory.output",
  });
  expect(table).toHaveTextContent("Pen");
  expect(content.mock.calls.map((call) => call[2])).toEqual([0, first.length]);
});

it("renders stored text parts for model thinking and preserves the raw text view", async () => {
  const user = userEvent.setup();
  const reasoning = JSON.stringify([
    { type: "text", text: "**Compare" },
    { type: "image_url", image_url: { url: "/private-image" } },
    { type: "text", text: " policies**" },
  ]);
  renderNode({ reasoning: body(reasoning) });
  const thinking = section("reasoning");
  const table = within(thinking).getByRole("table", {
    name: "trajectory.reasoning",
  });
  expect(
    within(table).getByRole("rowheader", { name: "reasoning" })
  ).toBeVisible();
  expect(within(table).getByText("Compare policies").tagName).toBe("STRONG");
  expect(table).not.toHaveTextContent("/private-image");
  await user.click(
    within(within(thinking).getByRole("radiogroup")).getByText(
      "trajectory.text"
    )
  );
  expect(thinking.querySelector("pre code")?.textContent).toBe(reasoning);
});

it.each([
  [
    "output",
    JSON.stringify({ content_parts: [{ type: "text", text: "**Visible**" }] }),
  ],
  ["output", JSON.stringify("**Visible**")],
  ["reasoning", "**Visible**"],
] as const)("renders historical %s bodies inside the table", (slot, value) => {
  renderNode({ [slot]: body(value) });
  const table = within(section(slot)).getByRole("table", {
    name: `trajectory.${slot}`,
  });
  expect(within(table).getByText("Visible").tagName).toBe("STRONG");
});

it("leaves tool calls and response metadata as literal JSON cells", () => {
  renderNode({
    output: body(
      JSON.stringify({
        choices: [
          {
            message: {
              content: null,
              tool_calls: [{ id: "call", name: "**Tool**" }],
            },
          },
        ],
        metadata: "**literal**",
      })
    ),
  });
  const output = section("output");
  const choices = within(output).getByRole("table", { name: "choices" });
  expect(
    within(choices).getByRole("rowheader", { name: "tool_calls" })
  ).toBeVisible();
  expect(choices).toHaveTextContent('[{"id":"call","name":"**Tool**"}]');
  expect(output).toHaveTextContent('"**literal**"');
  expect(output.querySelector("strong")).toBeNull();
});

it("displays the unavailable state for missing model thinking", () => {
  renderNode({});
  const thinking = section("reasoning");
  expect(thinking).toHaveTextContent("trajectory.bodyUnavailable");
  expect(
    within(thinking).queryByRole("radio", { name: "trajectory.table" })
  ).toBeNull();
});

it.each(["{}", "null", JSON.stringify("x".repeat(128 * 1024 + 1))])(
  "falls back to JSON when the model response is empty or beyond the preview limit",
  (raw) => {
    renderNode({ output: body(raw) });
    const output = section("output");
    expect(
      within(output).queryByRole("radio", { name: "trajectory.table" })
    ).toBeNull();
    expect(output.querySelector("pre code")?.textContent).toBe(raw);
  }
);

it("does not interpret HTML or fetch Markdown images from a model result", () => {
  const text =
    "**Visible**\n\n<div id='raw-html'>HTML</div>\n\n![Image](/markdown.png)";
  renderNode({ output: body(text) });
  const output = section("output");
  expect(within(output).getByText("Visible").tagName).toBe("STRONG");
  expect(output.querySelector("#raw-html, img")).toBeNull();
});

it.each(["agent", "tool", "phase", "unknown"])(
  "offers only text and JSON for %s bodies",
  async (kind) => {
    const user = userEvent.setup();
    const raw = JSON.stringify({ content: markdown, ok: false });
    renderNode({
      kind,
      input: body(raw),
      output: body(raw),
      reasoning: body(raw),
    });
    for (const slot of ["input", "reasoning", "output"] as const) {
      const display = section(slot);
      const modes = within(within(display).getByRole("radiogroup"));
      expect(modes.getAllByRole("radio")).toHaveLength(2);
      expect(within(display).queryByRole("table")).toBeNull();
      expect(
        within(display).queryByRole("heading", { name: "Inventory" })
      ).toBeNull();
      expect(display.querySelector("pre code")?.textContent).toBe(
        JSON.stringify(JSON.parse(raw), null, 2)
      );
      await user.click(modes.getByText("trajectory.text"));
      expect(display.querySelector("pre code")?.textContent).toBe(raw);
    }
  }
);
