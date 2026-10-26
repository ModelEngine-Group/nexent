import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SourceMetadata } from "@/components/common/sourceMetadata";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

describe("source metadata inspection", () => {
  afterEach(() => vi.restoreAllMocks());
  it("defers JSON serialization and nested descendants until requested", async () => {
    const metadata = {
      title: "Example",
      nested: { deep: { leaf: "full nested value" } },
    };
    const stringify = vi.spyOn(JSON, "stringify");
    render(<SourceMetadata metadata={metadata} />);
    expect(
      stringify.mock.calls.filter(([value]) => value === metadata)
    ).toHaveLength(0);
    fireEvent.mouseEnter(
      screen.getByRole("button", { name: "chat.sources.showAttributes" })
    );
    const dialog = await screen.findByRole("dialog", {
      name: "chat.sources.attributes",
    });
    expect(
      stringify.mock.calls.filter(([value]) => value === metadata)
    ).toHaveLength(0);
    expect(dialog).not.toHaveTextContent("full nested value");
    const nested = screen.getByText("nested", {
      selector: "summary",
    }).parentElement!;
    (nested as HTMLDetailsElement).open = true;
    fireEvent(nested, new Event("toggle"));
    const deep = await screen.findByText("deep", { selector: "summary" });
    (deep.parentElement as HTMLDetailsElement).open = true;
    fireEvent(deep.parentElement!, new Event("toggle"));
    await waitFor(() =>
      expect(screen.getByText("full nested value")).toBeVisible()
    );
    fireEvent.click(screen.getByRole("tab", { name: "chat.sources.rawJson" }));
    await waitFor(() =>
      expect(
        stringify.mock.calls.filter(([value]) => value === metadata)
      ).toHaveLength(1)
    );
    expect(dialog.querySelector("pre")?.textContent).toBe(
      JSON.stringify(metadata, null, 2)
    );
    stringify.mockRestore();
  });

  it("preserves pinning, outside dismissal and Escape", async () => {
    render(<SourceMetadata metadata={{ title: "Pinned metadata" }} />);
    const trigger = screen.getByRole("button", {
      name: "chat.sources.showAttributes",
    });
    fireEvent.click(trigger);
    await waitFor(() => expect(screen.getByRole("dialog")).toBeVisible());
    fireEvent.mouseLeave(trigger);
    expect(screen.getByRole("dialog")).toBeVisible();
    fireEvent.pointerDown(document.body);
    await waitFor(() =>
      expect(trigger).toHaveAttribute("aria-expanded", "false")
    );
    fireEvent.click(trigger);
    fireEvent.keyDown(await screen.findByRole("dialog"), { key: "Escape" });
    await waitFor(() =>
      expect(trigger).toHaveAttribute("aria-expanded", "false")
    );
  });

  it("omits empty metadata and retains literal values", () => {
    const { rerender } = render(<SourceMetadata metadata={{}} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    rerender(
      <SourceMetadata
        metadata={{
          empty: "",
          zero: 0,
          bool: false,
          markup: "<script>literal</script>",
        }}
      />
    );
    expect(screen.getByRole("button")).toHaveTextContent('empty：""');
    expect(screen.getByRole("button")).toHaveTextContent("zero：0");
    expect(screen.getByRole("button")).toHaveTextContent("bool：false");
    expect(document.querySelector("script")).toBeNull();
  });
});
