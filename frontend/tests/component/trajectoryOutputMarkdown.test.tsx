// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { App } from "antd";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TrajectoryNodeDetail } from "@/app/observability/components/TrajectoryNodeDetail";
import { BodyCache } from "@/lib/trajectory";
import { trajectoryService } from "@/services/trajectoryService";
import type { ContentReference } from "@/types/trajectory";
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

function renderNode(output: ContentReference, kind = "model") {
  render(
    <App>
      <TrajectoryNodeDetail
        node={traceNode({ kind, input: body(markdown), output })}
        conversationId="1"
        cache={new BodyCache()}
        onParent={vi.fn()}
        onLoaded={vi.fn()}
      />
    </App>
  );
  return screen
    .getByRole("button", { name: "trajectory.output" })
    .closest("section")!;
}

beforeEach(() => content.mockReset());

describe("trajectory model response Markdown", () => {
  it("renders and copies the answer while preserving JSON and text views", async () => {
    const user = userEvent.setup();
    const response = {
      choices: [{ message: { content: markdown } }],
      usage: { total_tokens: 12 },
    };
    const text = JSON.stringify(response);
    const output = renderNode(body(text));

    expect(
      within(output).getByRole("heading", { name: "Inventory" })
    ).toBeVisible();
    expect(within(output).getByRole("table")).toHaveTextContent("Pen");
    expect(screen.getAllByRole("table")).toHaveLength(1);
    await user.click(
      within(output).getByRole("button", { name: "trajectory.copy" })
    );
    expect(await navigator.clipboard.readText()).toBe(markdown);

    const modes = within(within(output).getByRole("radiogroup"));
    await user.click(modes.getByText("JSON"));
    expect(output.querySelector("pre code")?.textContent).toBe(
      JSON.stringify(response, null, 2)
    );
    await user.click(modes.getByText("trajectory.text"));
    expect(output.querySelector("pre code")?.textContent).toBe(text);
    await user.click(modes.getByText("Markdown"));
    expect(within(output).getByRole("table")).toBeVisible();
  });

  it("renders the merged delta only after its final chunk is loaded", async () => {
    const text = JSON.stringify({
      choices: [{ delta: { content: markdown } }],
    });
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
    const output = renderNode(body(first, false));

    const source = await within(output).findByText(
      (_, element) =>
        element?.tagName === "CODE" && element.textContent!.includes("content")
    );
    expect(within(output).queryByText("Markdown")).not.toBeInTheDocument();
    fireEvent.wheel(source.closest("pre")!, { deltaY: 1 });
    expect(await within(output).findByRole("table")).toHaveTextContent("Pen");
    expect(content.mock.calls.map((call) => call[2])).toEqual([
      0,
      first.length,
    ]);
  });

  it.each([
    [
      "tool-only model response",
      "model",
      {
        choices: [{ message: { content: null, tool_calls: [{ id: "call" }] } }],
      },
    ],
    [
      "unknown node",
      "unknown",
      { choices: [{ message: { content: markdown } }] },
    ],
    [
      "response larger than the renderer budget",
      "model",
      "x".repeat(128 * 1024 + 1),
    ],
  ])("keeps the default JSON view for a %s", (_label, kind, response) => {
    const output = renderNode(body(JSON.stringify(response)), kind);
    expect(within(output).queryByText("Markdown")).not.toBeInTheDocument();
    expect(output.querySelector("pre code")?.textContent).toBe(
      JSON.stringify(response, null, 2)
    );
  });

  it("keeps the original spacing between text parts and excludes other parts", () => {
    const output = renderNode(
      body(
        JSON.stringify({
          choices: [
            {
              message: {
                content: [
                  { type: "text", text: "**One" },
                  { type: "text", text: " " },
                  { type: "image_url", image_url: { url: "/provider-image" } },
                  { type: "text", text: "answer**" },
                ],
              },
            },
          ],
        })
      )
    );

    expect(within(output).getByText("One answer").tagName).toBe("STRONG");
    expect(output.querySelector("img")).toBeNull();
  });

  it("does not interpret HTML or load images from a captured response", () => {
    const text =
      "**Visible**\n\n<div id='raw-html'>HTML</div>\n\n![Image](/markdown.png)";
    const output = renderNode(body(JSON.stringify(text)));

    expect(within(output).getByText("Visible").tagName).toBe("STRONG");
    expect(output.querySelector("#raw-html")).toBeNull();
    expect(output.querySelector("img")).toBeNull();
  });
});

describe("trajectory Markdown for agent, tool and phase outputs", () => {
  it("renders an agent's Markdown answer without changing the input view", () => {
    const output = renderNode(body(markdown), "agent");

    expect(within(output).getByRole("table")).toHaveTextContent("Pen");
    const input = screen
      .getByRole("button", { name: "trajectory.input" })
      .closest("section")!;
    expect(within(input).queryByRole("table")).not.toBeInTheDocument();
    expect(input.querySelector("pre code")?.textContent).toContain("Inventory");
  });

  it("renders a tool result object as key-value rows with nested JSON kept inline", () => {
    const output = renderNode(
      body(JSON.stringify({ ok: true, details: { count: 2 } })),
      "tool"
    );

    const table = within(output).getByRole("table");
    expect(
      within(table).getByRole("columnheader", {
        name: "trajectory.markdownField",
      })
    ).toBeVisible();
    expect(
      within(table).getByRole("row", { name: 'details {"count":2}' })
    ).toBeVisible();
  });

  it("keeps primitive values in array order", () => {
    const output = renderNode(body('["first",0,false,null]'), "tool");
    const table = within(output).getByRole("table");
    expect(
      within(table).getByRole("columnheader", {
        name: "trajectory.markdownIndex",
      })
    ).toBeVisible();
    expect(
      within(table)
        .getAllByRole("cell")
        .map((cell) => cell.textContent)
    ).toEqual(["1", "first", "2", "0", "3", "false", "4", "null"]);
  });

  it("turns tool records into columns without interpreting data values as Markdown", async () => {
    const user = userEvent.setup();
    const literal = "**A** | B\\C\nhttps://example.test";
    const raw = JSON.stringify([
      { item: literal, count: 2 },
      { item: "Pen", active: true },
    ]);
    const output = renderNode(body(raw), "tool");

    const table = within(output).getByRole("table");
    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((header) => header.textContent)
    ).toEqual(["item", "count", "active"]);
    expect(
      within(table).getByRole("cell", { name: literal.replace("\n", "\\n") })
    ).toBeVisible();
    expect(table.querySelector("strong, a")).toBeNull();
    await user.click(
      within(output).getByRole("button", { name: "trajectory.copy" })
    );
    expect(await navigator.clipboard.readText()).toContain(
      "| item | count | active |"
    );
    await user.click(
      within(within(output).getByRole("radiogroup")).getByText(
        "trajectory.text"
      )
    );
    expect(output.querySelector("pre code")?.textContent).toBe(raw);
  });

  it("renders the memory phase's steps as records", () => {
    const output = renderNode(
      body(
        JSON.stringify({
          steps: [
            { name: "memory.presearch", status: "success", duration_ms: 12 },
          ],
        })
      ),
      "phase"
    );

    const table = within(output).getByRole("table");
    expect(
      within(table).getByRole("columnheader", { name: "duration_ms" })
    ).toBeVisible();
    expect(
      within(table).getByRole("row", { name: "memory.presearch success 12" })
    ).toBeVisible();
  });

  it("tables Python records and keeps logs in a code block", () => {
    const logs = "first\n```\nlast";
    const output = renderNode(
      body(JSON.stringify({ output: [{ id: 17 }], logs })),
      "phase"
    );

    expect(within(output).getByRole("table")).toHaveTextContent("17");
    expect(output.querySelector("pre code")?.textContent).toBe(`${logs}\n`);
  });

  it.each(["[]", "{}", '[{"id":9007199254740993}]'])(
    "does not offer a table for an empty or unsafe JSON value: %s",
    (raw) => {
      const output = renderNode(body(raw), "tool");
      expect(within(output).queryByRole("table")).not.toBeInTheDocument();
      expect(
        within(output).queryByRole("radio", { name: "Markdown" })
      ).not.toBeInTheDocument();
    }
  );
});
