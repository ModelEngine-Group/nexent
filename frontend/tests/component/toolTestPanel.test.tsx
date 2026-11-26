// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import ToolTestPanel from "@/app/agents/components/capability/tool/ToolTestPanel";
import { parseToolInputs, validateTool } from "@/services/agentConfigService";
import type { Tool } from "@/types/agentConfig";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: "zh" } }),
}));
vi.mock("@/services/agentConfigService", () => ({
  parseToolInputs: vi.fn(),
  validateTool: vi.fn(),
  extractParameterNames: vi.fn(() => []),
}));
vi.mock("@/lib/logger", () => ({ default: { error: vi.fn() } }));

const tool: Tool = {
  id: "42",
  name: "analyze_image",
  source: "local",
  description: "Analyze an image",
  inputs: "image schema",
  initParams: [],
};
const props = {
  visible: true,
  tool,
  configParams: [
    {
      name: "model",
      type: "string" as const,
      required: false,
      value: "draft-model",
    },
  ],
  onClose: vi.fn(),
};

beforeEach(() => {
  vi.mocked(parseToolInputs).mockReturnValue({
    image_url: { type: "string", description: "Image URL", required: true },
  });
  vi.mocked(validateTool).mockReset();
  vi.mocked(validateTool).mockResolvedValue('{"ok":true}');
});

describe("bound knowledge in the shared tool test panel", () => {
  it.each([
    ["knowledge_base_search", "index_names"],
    ["aidp_search", "kds_list"],
  ] as const)(
    "passes the bound %s scope through the existing tool form",
    async (name, selectionParam) => {
      vi.mocked(parseToolInputs).mockReturnValue({
        query: { type: "string", description: "Search query", required: true },
        [selectionParam]: { type: "array" },
      });
      vi.mocked(validateTool).mockResolvedValue(
        '{"results":[{"text":"Keep your receipts."}]}'
      );
      render(
        <ToolTestPanel
          {...props}
          tool={{ ...tool, name }}
          configParams={[
            { name: "top_k", type: "number", required: false, value: 5 },
          ]}
          toolRequiresKbSelection
          toolKbType={name}
          boundKnowledgeIds={["policy", "other"]}
          testPanelKbIds={["policy"]}
          testPanelKbDisplayNames={["Travel policy"]}
        />
      );
      const run = screen.getByRole("button", {
        name: "agent.knowledge.test.run",
      });
      expect(run).toBeDisabled();
      expect(await screen.findByText("Travel policy")).toBeVisible();
      fireEvent.change(screen.getByPlaceholderText("Search query"), {
        target: { value: " receipts " },
      });
      await waitFor(() => expect(run).toBeEnabled());
      expect(validateTool).not.toHaveBeenCalled();
      fireEvent.click(run);
      await waitFor(() =>
        expect(validateTool).toHaveBeenCalledExactlyOnceWith(
          name,
          "local",
          "",
          { query: "receipts", [selectionParam]: ["policy"] },
          { top_k: 5, [selectionParam]: ["policy"] },
          "zh"
        )
      );
      expect(await screen.findByText(/Keep your receipts/)).toBeVisible();
    }
  );

  it("rejects a scope outside the binding when using the existing JSON mode", async () => {
    vi.mocked(parseToolInputs).mockReturnValue({
      query: { type: "string", description: "Search query" },
      index_names: { type: "array" },
    });
    render(
      <ToolTestPanel
        {...props}
        tool={{ ...tool, name: "knowledge_base_search" }}
        toolRequiresKbSelection
        boundKnowledgeIds={["policy"]}
        testPanelKbIds={["policy"]}
        testPanelKbDisplayNames={["Travel policy"]}
      />
    );
    fireEvent.click(await screen.findByText("JSON"));
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: '{"query":"receipts","index_names":["unbound"]}' },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "agent.knowledge.test.run" })
    );
    expect(
      await screen.findByText("agent.knowledge.test.invalidInputs")
    ).toBeVisible();
    expect(validateTool).not.toHaveBeenCalled();
  });

  it.each([
    ["knowledge_base_search", "index_names"],
    ["aidp_search", "kds_list"],
  ] as const)(
    "synchronizes %s JSON scope with the parent selection",
    async (name, scopeParam) => {
      vi.mocked(parseToolInputs).mockReturnValue({
        query: { type: "string", description: "Search query" },
        [scopeParam]: { type: "array" },
      });
      const boundIds = ["policy", "handbook"];
      const displayNames: Record<string, string> = {
        policy: "Travel Policy",
        handbook: "Staff Handbook",
      };
      const setScope = vi.fn();
      function Fixture() {
        const [ids, setIds] = useState(boundIds);
        return (
          <ToolTestPanel
            {...props}
            tool={{ ...tool, name }}
            configParams={[]}
            toolRequiresKbSelection
            toolKbType={name}
            boundKnowledgeIds={boundIds}
            testPanelKbIds={ids}
            testPanelKbDisplayNames={ids.map((id) => displayNames[id])}
            onTestPanelKbIdsChange={(nextIds) => {
              setScope(nextIds);
              setIds(nextIds);
            }}
          />
        );
      }
      render(<Fixture />);
      const editScope = (ids: string[]) =>
        fireEvent.change(screen.getByRole("textbox"), {
          target: {
            value: JSON.stringify({ query: "travel", [scopeParam]: ids }),
          },
        });
      const switchToForm = () =>
        fireEvent.click(screen.getByText("toolConfig.toolTest.form"));
      fireEvent.click(await screen.findByText("JSON"));
      editScope(["unbound"]);
      switchToForm();
      expect(
        await screen.findByText("agent.knowledge.test.invalidInputs")
      ).toBeVisible();
      expect(setScope).not.toHaveBeenCalled();
      expect(validateTool).not.toHaveBeenCalled();

      editScope(["handbook", "handbook"]);
      switchToForm();
      expect(await screen.findByText("Staff Handbook")).toBeVisible();
      expect(screen.queryByText("Travel Policy")).not.toBeInTheDocument();
      expect(setScope).toHaveBeenLastCalledWith(["handbook"]);
      const run = screen.getByRole("button", {
        name: "agent.knowledge.test.run",
      });
      await waitFor(() => expect(run).toBeEnabled());
      fireEvent.click(run);
      await waitFor(() =>
        expect(validateTool).toHaveBeenCalledExactlyOnceWith(
          name,
          "local",
          "",
          { query: "travel", [scopeParam]: ["handbook"] },
          { [scopeParam]: ["handbook"] },
          "zh"
        )
      );

      fireEvent.click(screen.getByText("JSON"));
      editScope([]);
      switchToForm();
      expect(setScope).toHaveBeenLastCalledWith([]);
      expect(screen.queryByText("Staff Handbook")).not.toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: "agent.knowledge.test.run" })
      ).toBeDisabled();
      expect(validateTool).toHaveBeenCalledTimes(1);
    }
  );
});

describe("tool testing in the split configuration dialog", () => {
  it("shows the empty result and runs with the current unsaved configuration", async () => {
    const { rerender } = render(<ToolTestPanel {...props} />);
    expect(
      screen.getByText("toolConfig.toolTest.emptyTitle")
    ).toBeInTheDocument();
    fireEvent.change(await screen.findByPlaceholderText("Image URL"), {
      target: { value: "https://example.com/image.png" },
    });
    rerender(
      <ToolTestPanel
        {...props}
        configParams={[{ ...props.configParams[0], value: "updated-model" }]}
      />
    );
    fireEvent.click(
      screen.getByRole("button", { name: "ui.localization.runTest" })
    );
    await waitFor(() =>
      expect(validateTool).toHaveBeenCalledWith(
        "analyze_image",
        "local",
        "",
        { image_url: "https://example.com/image.png" },
        { model: "updated-model" },
        "zh"
      )
    );
    expect(await screen.findByText(/"ok": true/)).toBeInTheDocument();
  });

  it("preserves input when switching between the form and JSON", async () => {
    render(<ToolTestPanel {...props} />);
    fireEvent.change(await screen.findByPlaceholderText("Image URL"), {
      target: { value: "https://example.com/a.png" },
    });
    fireEvent.click(screen.getByText("JSON"));
    expect(
      (screen.getByRole("textbox") as HTMLTextAreaElement).value
    ).toContain("https://example.com/a.png");
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: '{"image_url":"https://example.com/b.png"}' },
    });
    fireEvent.click(screen.getByText("toolConfig.toolTest.form"));
    expect(await screen.findByPlaceholderText("Image URL")).toHaveValue(
      "https://example.com/b.png"
    );
  });

  it("disables testing when the configuration is invalid", () => {
    render(<ToolTestPanel {...props} configInvalid />);
    expect(
      screen.getByRole("button", { name: "ui.localization.runTest" })
    ).toBeDisabled();
    expect(validateTool).not.toHaveBeenCalled();
  });

  it("shows service failures in the result area", async () => {
    vi.mocked(validateTool).mockRejectedValue(new Error("Tool unavailable"));
    render(<ToolTestPanel {...props} />);
    fireEvent.change(await screen.findByPlaceholderText("Image URL"), {
      target: { value: "https://example.com/a.png" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "ui.localization.runTest" })
    );
    expect(
      await screen.findByText(/Test failed:.*Tool unavailable/)
    ).toBeInTheDocument();
  });

  it("keeps manual JSON available when the tool has no input schema", async () => {
    vi.mocked(parseToolInputs).mockReturnValue({});
    render(<ToolTestPanel {...props} />);
    expect(await screen.findByRole("textbox")).toHaveValue("{}");
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "invalid" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "ui.localization.runTest" })
    );
    expect(await screen.findByText(/Invalid JSON format/)).toBeInTheDocument();
    expect(validateTool).not.toHaveBeenCalled();
  });
});
