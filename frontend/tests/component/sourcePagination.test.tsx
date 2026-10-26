// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  SourcesPanel,
  type PanelSourceItem,
} from "@/app/newchat/ui/sources-panel";
import { getSourceLabel } from "@/lib/source";

vi.mock("@/lib/source", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/source")>();
  return { ...actual, getSourceLabel: vi.fn(actual.getSourceLabel) };
});

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/app/newchat/ui/authenticated-image", () => ({
  AuthenticatedImage: ({ alt }: { alt: string }) => <img alt={alt} />,
}));
const sources: PanelSourceItem[] = Array.from({ length: 45 }, (_, index) => ({
  title: `Source ${index + 1}`,
  citeIndex: index + 1,
  toolSign: "a",
  displayIndex: 100 - index,
  text: "Evidence",
  sourceMetadata: { field: `value-${index + 1}` },
}));

describe("source inspection pagination", () => {
  it("updates only the previous and next selected cards on the same page", () => {
    const props = { sources, images: [], open: true, onClose: vi.fn() };
    const view = render(
      <SourcesPanel {...props} selectedCitationKey="a45" selectionToken={{}} />
    );
    vi.mocked(getSourceLabel).mockClear();
    view.rerender(
      <SourcesPanel {...props} selectedCitationKey="a44" selectionToken={{}} />
    );
    const updated = new Set(
      vi
        .mocked(getSourceLabel)
        .mock.calls.map(([item]) => (item as PanelSourceItem).citeIndex)
    );
    expect(updated).toEqual(new Set([44, 45]));
  });
  it("follows actual source keys and repeated selections while keeping manual paging", async () => {
    const token = {};
    const props = {
      sources,
      images: [],
      open: true,
      onClose: vi.fn(),
      selectedCitationKey: "a45",
      selectionToken: token,
    };
    const view = render(<SourcesPanel {...props} />);
    expect(screen.getByText("Source 45")).toBeInTheDocument();
    expect(
      view.container.querySelectorAll("[data-source-metadata]")
    ).toHaveLength(5);
    fireEvent.click(screen.getByTitle("1"));
    expect(screen.getByText("Source 1")).toBeInTheDocument();
    expect(screen.queryByText("Source 45")).not.toBeInTheDocument();
    view.rerender(<SourcesPanel {...props} selectionToken={{}} />);
    expect(screen.getByText("Source 45")).toBeInTheDocument();
    expect(
      view.container.querySelector('[data-citation-key="a45"]')
    ).toHaveAttribute("data-citation-selected", "true");
    view.rerender(
      <SourcesPanel
        {...props}
        sources={sources.slice(0, 2)}
        selectionToken={{}}
      />
    );
    expect(screen.getByText("Source 1")).toBeInTheDocument();
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
  });

  it("uses independent source/image pages and supports image-only messages", async () => {
    const images = sources.map((source) => ({
      ...source,
      title: `Image ${source.citeIndex}`,
      url: `https://example.invalid/${source.citeIndex}.png`,
      isImage: true,
      toolSign: "b",
    }));
    const view = render(
      <SourcesPanel
        sources={sources}
        images={images}
        open
        selectedCitationKey="b45"
        selectionToken={{}}
        onClose={vi.fn()}
      />
    );
    expect(screen.getByAltText("Image 45")).toBeInTheDocument();
    expect(screen.getAllByRole("img", { name: /^Image / })).toHaveLength(5);
    fireEvent.click(screen.getByRole("tab", { name: /chat.sources.sources/ }));
    expect(screen.getByText("Source 1")).toBeInTheDocument();
    fireEvent.click(screen.getByTitle("2"));
    expect(screen.getByText("Source 21")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: /chat.sources.images/ }));
    await waitFor(() =>
      expect(screen.getByAltText("Image 1")).toBeInTheDocument()
    );
    view.rerender(
      <SourcesPanel
        sources={[]}
        images={images.slice(0, 1)}
        open
        onClose={vi.fn()}
        selectionToken={{}}
      />
    );
    expect(screen.getByAltText("Image 1")).toBeInTheDocument();
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
  });
});
