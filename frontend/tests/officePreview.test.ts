import assert from "node:assert/strict";
import test from "node:test";

import {
  decodeServedFileName,
  getFileExtension,
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
