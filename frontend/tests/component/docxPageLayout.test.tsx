// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import JSZip from "jszip";
import { renderAsync } from "docx-preview";
import { expect, test } from "vitest";
import { applyDocxPageDefaults } from "@/lib/officePreview";

async function renderDocument(section = "") {
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
    `<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>你好！这是一个简单的Word文档。</w:t></w:r></w:p>${section}</w:body></w:document>`
  );
  const body = document.createElement("div");
  const styles = document.createElement("div");
  document.body.append(body, styles);
  await renderAsync(
    await zip.generateAsync({ type: "arraybuffer" }),
    body,
    styles,
    { inWrapper: true, renderAltChunks: false }
  );
  return {
    body,
    styles,
    page: body.querySelector<HTMLElement>("section.docx")!,
  };
}

test("gives a real generated DOCX without section metadata a full paper page and margins", async () => {
  const { body, styles, page } = await renderDocument();
  try {
    expect(page.style.width).toBe("");
    expect(page.style.minHeight).toBe("");
    applyDocxPageDefaults(body);
    expect(page.style.width).toBe("min(210mm, 100%)");
    expect(page.style.minHeight).toBe("297mm");
    expect(page.style.paddingTop).toBe("25.4mm");
    expect(page.textContent).toContain("这是一个简单的Word文档");
  } finally {
    body.remove();
    styles.remove();
  }
});

test("preserves explicit landscape dimensions and zero/custom margins from the document", async () => {
  const { body, styles, page } = await renderDocument(
    '<w:sectPr><w:pgSz w:w="16838" w:h="11906" w:orient="landscape"/><w:pgMar w:top="0" w:right="720" w:bottom="1440" w:left="720"/></w:sectPr>'
  );
  try {
    const original = page.getAttribute("style");
    expect(page.style.width).not.toBe("");
    expect(page.style.minHeight).not.toBe("");
    applyDocxPageDefaults(body);
    expect(page.getAttribute("style")).toBe(original);
  } finally {
    body.remove();
    styles.remove();
  }
});

test("fills only missing values and leaves non-document content untouched", () => {
  const body = document.createElement("div");
  body.innerHTML =
    '<div class="docx-wrapper"><section class="docx" style="width: 500px; height: 700px; padding-top: 0px"><p>One</p></section><section class="docx"><p>Two</p></section></div><section style="width: 300px">Other</section>';
  applyDocxPageDefaults(body);
  const pages = body.querySelectorAll<HTMLElement>("section.docx");
  expect(pages[0].style.width).toBe("500px");
  expect(pages[0].style.height).toBe("700px");
  expect(pages[0].style.minHeight).toBe("");
  expect(pages[0].style.paddingTop).toBe("0px");
  expect(pages[0].style.paddingRight).toBe("25.4mm");
  expect(pages[1].style.minHeight).toBe("297mm");
  expect(
    body.querySelector<HTMLElement>("section:not(.docx)")!.style.cssText
  ).toBe("width: 300px;");
  const once = body.innerHTML;
  applyDocxPageDefaults(body);
  expect(body.innerHTML).toBe(once);
});
