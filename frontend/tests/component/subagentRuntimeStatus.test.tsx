import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SubAgentContainer } from "../../app/[locale]/newchat/ui/subagent";
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

describe("native child status in legacy invocation cards", () => {
  it.each(["failed", "stopped"] as const)(
    "does not label a %s native child as completed",
    (status) => {
      render(
        <SubAgentContainer
          agentName="Child"
          depth={1}
          isRunning={false}
          executionStatus={status}
        />
      );
      expect(screen.getByText(`chat.executionStatus.${status}`)).toBeVisible();
      expect(screen.queryByText("Completed")).toBeNull();
    }
  );
  it("preserves the legacy completed label without a runtime result", () => {
    render(
      <SubAgentContainer agentName="Legacy" depth={1} isRunning={false} />
    );
    expect(screen.getByText("Completed")).toBeVisible();
  });
});
