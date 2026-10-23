// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RawStreamPreviewViewer } from "@/components/common/rawStreamPreviewViewer";
import { fetchPreviewBlobWithMeta } from "@/lib/filePreviewUtils";
import { pptxGroupRotationStyle } from "@/lib/officePreview";
import { renderAsync } from "docx-preview";

const { parseMock } = vi.hoisted(() => ({ parseMock: vi.fn() }));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("@/lib/logger", () => ({
  default: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
}));

// Only the fetch is replaced: the error types the viewer reacts to stay real.
vi.mock("@/lib/filePreviewUtils", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/lib/filePreviewUtils")>();
  return { ...actual, fetchPreviewBlobWithMeta: vi.fn() };
});

// docx-preview writes into the container it is given; the stand-in does the
// same so the hardening the viewer applies afterwards is exercised.
vi.mock("docx-preview", () => ({
  renderAsync: vi.fn(async (_data: unknown, body: HTMLElement) => {
    body.innerHTML =
      '<a href="javascript:alert(1)">run</a><p>docx body</p>' +
      '<iframe srcdoc="<script>alert(1)</script>"></iframe>';
  }),
}));

vi.mock("pptxtojson", () => ({ parse: parseMock }));

/**
 * jsdom's Blob has no `arrayBuffer`, and the viewer only ever asks the payload
 * for bytes, so the fetch stand-in answers with just that shape.
 */
const servedDocument = (fileName: string) => ({
  blob: {
    arrayBuffer: async () => new TextEncoder().encode("bytes").buffer,
    text: async () => "bytes",
  },
  fileName,
  mimeType: "",
});

const SLIDE_SIZE = { width: 960, height: 540 };

/** A group holding a text box and a picture, the only thing on its slide. */
const SLIDE_GROUP = {
  type: "group",
  id: "group-1",
  left: 100,
  top: 50,
  width: 400,
  height: 200,
  rotate: 0,
  order: 0,
  isFlipH: false,
  isFlipV: false,
  elements: [
    {
      type: "text",
      id: "text-1",
      left: 120,
      top: 70,
      width: 300,
      height: 60,
      order: 0,
      content: "<p>grouped text</p>",
    },
    {
      type: "image",
      id: "image-1",
      left: 120,
      top: 150,
      width: 80,
      height: 80,
      order: 1,
      base64: "data:image/png;base64,AAAA",
    },
  ],
};

const slideWithGroup = (rotate: number) => ({
  size: SLIDE_SIZE,
  slides: [{ fill: undefined, elements: [{ ...SLIDE_GROUP, rotate }] }],
});

describe("RawStreamPreviewViewer", () => {
  beforeEach(() => {
    vi.mocked(fetchPreviewBlobWithMeta).mockReset();
    parseMock.mockReset();
    vi.mocked(renderAsync).mockClear();
  });

  it("keeps embedded docx HTML out of the preview", async () => {
    vi.mocked(fetchPreviewBlobWithMeta).mockResolvedValue(
      servedDocument("report.docx") as never
    );

    render(
      <RawStreamPreviewViewer url="/api/preview" fileName="report.docx" />
    );

    expect(await screen.findByText("docx body")).toBeInTheDocument();

    // altChunk markup reaches the DOM through an unsandboxed srcdoc iframe and
    // never passes the sanitizer, so the option has to stay off.
    const options = vi.mocked(renderAsync).mock.calls[0]?.[3] as {
      renderAltChunks?: boolean;
    };
    expect(options?.renderAltChunks).toBe(false);
    // The link pass still runs over whatever docx-preview produced.
    expect(document.querySelector("a")?.hasAttribute("href")).toBe(false);
  });

  it("renders the children of a pptx group", async () => {
    vi.mocked(fetchPreviewBlobWithMeta).mockResolvedValue(
      servedDocument("deck.pptx") as never
    );
    parseMock.mockResolvedValue(slideWithGroup(0));

    render(<RawStreamPreviewViewer url="/api/preview" fileName="deck.pptx" />);

    // The group is the only element on the slide: dropping it leaves the slide
    // blank, which is what the previous switch did.
    expect(await screen.findByText("grouped text")).toBeInTheDocument();
    expect(
      document.querySelector('img[src="data:image/png;base64,AAAA"]')
    ).not.toBeNull();
  });

  it("anchors a rotated pptx group around its own centre", () => {
    // Group centre: (100 + 400 / 2) / 960 and (50 + 200 / 2) / 540.
    expect(
      pptxGroupRotationStyle({ ...SLIDE_GROUP, rotate: 90 }, SLIDE_SIZE)
    ).toEqual({
      transform: "rotate(90deg)",
      transformOrigin: "31.25% 27.77777777777778%",
    });
    // Without a rotation the children keep their own absolute layout.
    expect(
      pptxGroupRotationStyle({ ...SLIDE_GROUP, rotate: 0 }, SLIDE_SIZE)
    ).toBeUndefined();
  });
});
