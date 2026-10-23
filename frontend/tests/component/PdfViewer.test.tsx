// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PDF_DOCUMENT_OPTIONS } from "@/lib/pdfPreviewOptions.mjs";

const { documentMock } = vi.hoisted(() => ({
  documentMock: vi.fn<(props: Record<string, unknown>) => null>(() => null),
}));

vi.mock("react-pdf", () => ({
  Document: documentMock,
  Page: () => null,
  pdfjs: { GlobalWorkerOptions: {} },
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import { PdfViewer } from "@/components/common/PdfViewer";

describe("PdfViewer document resources", () => {
  it("passes stable local font and CMap options to React-PDF across URL changes", () => {
    const view = render(
      <PdfViewer url="blob:chinese" fileName="chinese.pdf" />
    );
    expect(documentMock.mock.calls.at(-1)?.[0]).toEqual(
      expect.objectContaining({
        file: "blob:chinese",
        options: PDF_DOCUMENT_OPTIONS,
      })
    );
    expect(PDF_DOCUMENT_OPTIONS.cMapUrl).toMatch(/\/pdfjs\/cmaps\/$/);
    expect(PDF_DOCUMENT_OPTIONS.cMapPacked).toBe(true);
    expect(PDF_DOCUMENT_OPTIONS.standardFontDataUrl).toMatch(
      /\/pdfjs\/standard_fonts\/$/
    );
    view.rerender(<PdfViewer url="blob:another" fileName="another.pdf" />);
    const props = documentMock.mock.calls.at(-1)?.[0];
    expect(props?.options).toBe(PDF_DOCUMENT_OPTIONS);
  });
});
