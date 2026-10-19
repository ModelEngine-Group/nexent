// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import AgentAvatarOptions from "../../app/[locale]/agents/[agentId]/components/agent-avatar-options";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: { name?: string }) => {
      if (key === "agent.avatar.choose")
        return `Choose ${options?.name} avatar`;
      const labels: Record<string, string> = {
        "agent.highFidelity.defaultAvatars": "Preset avatars",
        "agent.avatar.sparkles": "Sparkles",
        "agent.avatar.bot": "Robot",
        "agent.avatar.wand": "Wand",
        "agent.avatar.lightbulb": "Lightbulb",
        "agent.avatar.zap": "Lightning",
      };
      return labels[key] ?? key;
    },
  }),
}));

describe("AgentAvatarOptions", () => {
  it("shows all five legacy icons, marks the current choice and forwards the selected SVG", () => {
    const onSelect = vi.fn();
    render(
      <AgentAvatarOptions
        disabled={false}
        selectedKey="bot"
        onSelect={onSelect}
      />
    );
    expect(screen.getAllByRole("button")).toHaveLength(5);
    expect(
      screen.getByRole("button", { name: "Choose Robot avatar" })
    ).toHaveAttribute("aria-pressed", "true");
    const wand = screen.getByRole("button", { name: "Choose Wand avatar" });
    expect(wand).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(wand);
    expect(onSelect).toHaveBeenCalledWith(
      "wand",
      wand.querySelector("svg.lucide-wand")
    );
  });

  it("prevents selection while read-only or uploading", () => {
    const onSelect = vi.fn();
    render(<AgentAvatarOptions disabled onSelect={onSelect} />);
    for (const button of screen.getAllByRole("button")) {
      expect(button).toBeDisabled();
      fireEvent.click(button);
    }
    expect(onSelect).not.toHaveBeenCalled();
  });
});
