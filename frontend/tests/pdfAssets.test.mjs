// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import {
  mkdtempSync,
  mkdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { preparePdfAssets } from "../scripts/prepare-pdf-assets.mjs";

test("copies both resource directories and refreshes them on repeated preparation", (t) => {
  const temporary = mkdtempSync(path.join(os.tmpdir(), "nexent-pdf-assets-"));
  t.after(() => rmSync(temporary, { recursive: true, force: true }));
  const packageDirectory = path.join(temporary, "package");
  const publicDirectory = path.join(temporary, "public");
  for (const directory of ["cmaps", "standard_fonts"]) {
    mkdirSync(path.join(packageDirectory, directory), { recursive: true });
    writeFileSync(
      path.join(packageDirectory, directory, "resource"),
      directory
    );
  }
  writeFileSync(path.join(temporary, "unrelated"), "preserved");
  preparePdfAssets({ packageDirectory, publicDirectory });
  for (const directory of ["cmaps", "standard_fonts"]) {
    assert.equal(
      readFileSync(
        path.join(publicDirectory, "pdfjs", directory, "resource"),
        "utf8"
      ),
      directory
    );
    writeFileSync(
      path.join(packageDirectory, directory, "resource"),
      "updated"
    );
  }
  preparePdfAssets({ packageDirectory, publicDirectory });
  for (const directory of ["cmaps", "standard_fonts"]) {
    assert.equal(
      readFileSync(
        path.join(publicDirectory, "pdfjs", directory, "resource"),
        "utf8"
      ),
      "updated"
    );
  }
  assert.equal(
    readFileSync(path.join(temporary, "unrelated"), "utf8"),
    "preserved"
  );
});

test("fails preparation when required package resources are absent", (t) => {
  const temporary = mkdtempSync(path.join(os.tmpdir(), "nexent-pdf-missing-"));
  t.after(() => rmSync(temporary, { recursive: true, force: true }));
  assert.throws(
    () =>
      preparePdfAssets({
        packageDirectory: temporary,
        publicDirectory: path.join(temporary, "public"),
      }),
    { code: "ENOENT" }
  );
  mkdirSync(path.join(temporary, "cmaps"));
  assert.throws(
    () =>
      preparePdfAssets({
        packageDirectory: temporary,
        publicDirectory: path.join(temporary, "public"),
      }),
    { code: "ENOENT" }
  );
});

for (const basePath of ["/", "/nexent"]) {
  test(`document options use local resources for base path ${basePath}`, () => {
    const result = execFileSync(
      process.execPath,
      [
        "--input-type=module",
        "-e",
        "import {PDF_DOCUMENT_OPTIONS} from './lib/pdfPreviewOptions.mjs'; process.stdout.write(JSON.stringify(PDF_DOCUMENT_OPTIONS));",
      ],
      {
        cwd: new URL("../", import.meta.url),
        env: { ...process.env, NEXT_PUBLIC_BASE_PATH: basePath },
        encoding: "utf8",
      }
    );
    const prefix = basePath === "/" ? "" : basePath;
    assert.deepEqual(JSON.parse(result), {
      rangeChunkSize: 65536,
      cMapUrl: `${prefix}/pdfjs/cmaps/`,
      cMapPacked: true,
      standardFontDataUrl: `${prefix}/pdfjs/standard_fonts/`,
    });
  });
}
