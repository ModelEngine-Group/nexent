import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
vi.mock("@assistant-ui/react", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@assistant-ui/react")>()),
  useAuiState: (selector: (state: { message: { content: unknown[] } }) => unknown) =>
    selector({ message: { content: [] } }),
}));
vi.mock("../../app/[locale]/newchat/ui/sources-panel-context", () => ({
  useSourcesPanel: () => ({ setSources: vi.fn(), setOpen: vi.fn() }),
}));
import { ToolFallback } from "../../app/[locale]/newchat/ui/tool-fallback";
it.each([true, false])(
  "uses the common tool card for isError=%s even after a completed run",
  (isError) => {
    render(
      <ToolFallback
        {...({
          toolName: "mcp",
          toolCallId: "id",
          args: {},
          argsText: "{}",
          result: "Exact result",
          isError,
          status: { type: "complete" },
        } as any)}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: "Used tool: mcp" }));
    expect(screen.getAllByText("Exact result").length).toBeGreaterThan(0);
    if (isError) expect(screen.getByText("Error:")).toBeVisible();
    else expect(screen.queryByText("Error:")).toBeNull();
  }
);
