// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import assert from "node:assert/strict";
import test from "node:test";

import {
  decodeServedFileName,
  getFileExtension,
  officeHtmlToText,
  resolveStreamPreviewKind,
  // @ts-expect-error -- Node requires the extension for this standalone test.
} from "../lib/officePreview.ts";

test("reads the extension of ordinary, dotted and extension-only names", () => {
  assert.equal(getFileExtension("report.pdf"), "pdf");
  assert.equal(getFileExtension("report.PDF"), "pdf");
  assert.equal(getFileExtension("archive.tar.gz"), "gz");
  assert.equal(getFileExtension("报告.docx"), "docx");
  // A name that is only an extension still identifies the format.
  assert.equal(getFileExtension(".pdf"), "pdf");
  assert.equal(getFileExtension("no-extension"), "");
  assert.equal(getFileExtension("trailing."), "");
  assert.equal(getFileExtension(""), "");
});

test("decodes the URI-encoded served file name", () => {
  assert.equal(decodeServedFileName("report.pdf"), "report.pdf");
  // The backend cannot put a Chinese name on a latin-1 header, so it encodes it.
  assert.equal(decodeServedFileName("%E6%8A%A5%E5%91%8A.pdf"), "报告.pdf");
  assert.equal(decodeServedFileName("  report.pdf  "), "report.pdf");
  // A literal `%` that is not an escape sequence travelled verbatim.
  assert.equal(decodeServedFileName("100%.pdf"), "100%.pdf");
  assert.equal(decodeServedFileName(""), undefined);
  assert.equal(decodeServedFileName(null), undefined);
  assert.equal(decodeServedFileName(undefined), undefined);
});

test("resolves the renderer from the name the server actually served", () => {
  // The served name wins over the uploaded one: a converted file is reported as
  // a PDF even though the upload was a legacy Office format.
  assert.equal(resolveStreamPreviewKind("report.pdf", "doc"), "pdf");
  assert.equal(resolveStreamPreviewKind("report.docx"), "docx");
  assert.equal(resolveStreamPreviewKind("sheet.xlsx"), "xlsx");
  assert.equal(resolveStreamPreviewKind("deck.pptx"), "pptx");
  assert.equal(resolveStreamPreviewKind("notes.txt"), "text");
  assert.equal(resolveStreamPreviewKind("photo.png"), "image");
});

test("falls back to the type hint and the response MIME type", () => {
  // No usable suffix: the uploaded type and then the response MIME decide.
  assert.equal(resolveStreamPreviewKind("report", "xlsx"), "xlsx");
  assert.equal(
    resolveStreamPreviewKind("report", undefined, "application/pdf"),
    "pdf"
  );
  assert.equal(
    resolveStreamPreviewKind("report", undefined, "text/plain; charset=utf-8"),
    "text"
  );
  assert.equal(
    resolveStreamPreviewKind("report", undefined, "image/png"),
    "image"
  );
  assert.equal(resolveStreamPreviewKind("report"), "unsupported");
  // A MIME type cannot rescue a format the browser has no renderer for.
  assert.equal(
    resolveStreamPreviewKind("report.doc", undefined, "application/msword"),
    "unsupported"
  );
});

test("converts Office markup to plain text without a DOM", () => {
  // Node has no `document`, so this exercises the parser-free fallback that
  // server-side rendering and these tests rely on.
  assert.equal(officeHtmlToText("<p>第一段</p>"), "第一段");
  assert.equal(officeHtmlToText("<p>a</p><p>b</p>"), "a\nb");
  assert.equal(officeHtmlToText("a<br/>b"), "a\nb");
  assert.equal(
    officeHtmlToText('<div style="color: red">styled</div>'),
    "styled"
  );
  assert.equal(officeHtmlToText(""), "");
});

test("never leaves a tag behind, even for overlapping angle brackets", () => {
  // A tag-matching regex answers this input with another tag; the scan cannot,
  // because it never emits the characters that delimit one.
  const echoed = officeHtmlToText("<<script>script>alert(1)</script>");
  assert.ok(!echoed.includes("<"), echoed);
  assert.ok(echoed.includes("alert(1)"), echoed);
});
