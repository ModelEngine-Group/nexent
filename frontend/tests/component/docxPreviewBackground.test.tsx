// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { render, waitFor } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import JSZip from "jszip";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { RawStreamPreviewViewer } from "@/components/common/rawStreamPreviewViewer";
import { fetchPreviewBlobWithMeta } from "@/lib/filePreviewUtils";
import log from "@/lib/logger";
import styles from "@/components/common/rawStreamPreviewViewer.module.css";

let stylesheet: HTMLStyleElement;
beforeEach(() => {
  // Apply the actual module rules with their exported scope in jsdom.
  const css = readFileSync(
    resolve(
      dirname(fileURLToPath(import.meta.url)),
      "../../components/common/rawStreamPreviewViewer.module.css"
    ),
    "utf8"
  );
  stylesheet = document.createElement("style");
  stylesheet.textContent = css
    .replace(/:global\(([^)]+)\)/g, "$1")
    .replaceAll(".docxPages", `.${styles.docxPages}`);
  document.head.append(stylesheet);
});
afterEach(() => stylesheet?.remove());

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/lib/logger", () => ({
  default: { error: vi.fn(), warn: vi.fn(), info: vi.fn(), debug: vi.fn() },
}));
vi.mock("@/lib/filePreviewUtils", async (original) => ({
  ...(await original<typeof import("@/lib/filePreviewUtils")>()),
  fetchPreviewBlobWithMeta: vi.fn(),
}));

async function documentBytes(background?: string) {
  const zip = new JSZip();
  zip.file(
    "[Content_Types].xml",
    `<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>`
  );
  zip.file(
    "_rels/.rels",
    `<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>`
  );
  zip.file(
    "word/document.xml",
    `<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">${background ? `<w:background w:color="${background}"/>` : ""}<w:body><w:p><w:r><w:t>Document paper</w:t></w:r></w:p><w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr></w:body></w:document>`
  );
  return zip.generateAsync({ type: "arraybuffer" });
}

test.each([
  [undefined, "rgb(255, 255, 255)"],
  ["FFEECC", "rgb(255, 238, 204)"],
])(
  "real DOCX rendering uses paper color %s instead of a transparent page",
  async (background, expected) => {
    const bytes = await documentBytes(background);
    vi.mocked(fetchPreviewBlobWithMeta).mockResolvedValue({
      blob: { arrayBuffer: async () => bytes },
      fileName: "report.docx",
      mimeType: "",
    } as never);
    const { container } = render(
      <RawStreamPreviewViewer url="/preview" fileName="report.docx" />
    );
    await waitFor(() => {
      expect(
        vi.mocked(log.error).mock.calls.map((call) => String(call[1]))
      ).toEqual([]);
      const page = container.querySelector(
        "section.docx"
      ) as HTMLElement | null;
      expect(page).not.toBeNull();
      expect(page?.textContent).toContain("Document paper");
      expect(window.getComputedStyle(page!).backgroundColor).toBe(expected);
      expect(window.getComputedStyle(page!).boxShadow).toBe("none");
      const wrapper = page!.parentElement!;
      expect(window.getComputedStyle(wrapper).backgroundColor).toBe(
        "rgba(0, 0, 0, 0)"
      );
      expect(window.getComputedStyle(wrapper).padding).toBe("0px");
    });
  }
);
