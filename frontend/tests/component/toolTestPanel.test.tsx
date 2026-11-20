// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

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
