// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import http from "node:http";
import { createRequire } from "node:module";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { preparePdfAssets } from "../../../frontend/scripts/prepare-pdf-assets.mjs";

const caseDirectory = fileURLToPath(new URL("./", import.meta.url));
const frontend = fileURLToPath(new URL("../../../frontend/", import.meta.url));
const require = createRequire(path.join(frontend, "package.json"));
const { chromium } = require("@playwright/test");
const packageDirectory = path.dirname(
  require.resolve("pdfjs-dist/package.json"),
);
const fixture = path.join(caseDirectory, "chinese_sample.pdf");
const digest = () =>
  createHash("sha256").update(readFileSync(fixture)).digest("hex");

test("PDF-PREVIEW-D1-001 renders Chinese glyphs with local assets at both deployment paths", async (t) => {
  const temporary = mkdtempSync(path.join(os.tmpdir(), "nexent-pdf-render-"));
  t.after(() => rmSync(temporary, { recursive: true, force: true }));
  const before = digest();
  preparePdfAssets({ publicDirectory: temporary });
  const browser = await chromium.launch({ headless: true });
  t.after(() => browser.close());

  for (const prefix of ["", "/nexent"]) {
    const requests = [];
    const server = http.createServer((req, res) => {
      const url = new URL(req.url, "http://localhost");
      requests.push(url.pathname);
      if (prefix && !url.pathname.startsWith(`${prefix}/`)) {
        res.writeHead(404).end();
        return;
      }
      const pathname = url.pathname.slice(prefix.length);
      let file;
      if (pathname === "/") {
        res.setHeader("Content-Type", "text/html");
        res.end('<html><body><canvas id="pdf"></canvas></body></html>');
        return;
      }
      if (pathname === "/sample.pdf") file = fixture;
      if (pathname === "/modules/pdfPreviewOptions.mjs")
        file = path.join(frontend, "lib/pdfPreviewOptions.mjs");
      if (pathname === "/base-path.mjs")
        file = path.join(frontend, "base-path.mjs");
      if (["/pdf.mjs", "/pdf.worker.mjs"].includes(pathname))
        file = path.join(packageDirectory, "build", pathname.slice(1));
      if (/^\/pdfjs\/(cmaps|standard_fonts)\/[a-zA-Z0-9_.-]+$/.test(pathname))
        file = path.join(temporary, pathname.slice(1));
      if (!file) {
        res.writeHead(404).end();
        return;
      }
      try {
        res.setHeader(
          "Content-Type",
          file.endsWith(".mjs")
            ? "text/javascript"
            : "application/octet-stream",
        );
        res.end(readFileSync(file));
      } catch {
        res.writeHead(404).end();
      }
    });
    await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
    const origin = `http://127.0.0.1:${server.address().port}`;
    try {
      for (const configured of [true, false]) {
        const page = await browser.newPage();
        const failures = [];
        const warnings = [];
        await page.route("**/*", (route) => {
          if (!route.request().url().startsWith(`${origin}/`)) {
            failures.push(route.request().url());
            return route.abort();
          }
          return route.continue();
        });
        page.on("response", (response) => {
          if (!response.ok())
            failures.push(`${response.status()} ${response.url()}`);
        });
        page.on("console", (message) => warnings.push(message.text()));
        try {
          await page.goto(`${origin}${prefix}/`);
          const observed = await page.evaluate(
            async ({ prefix, configured }) => {
              // Vary the same build-time substitution used by Next without editing modules.
              globalThis.process = { env: { NEXT_PUBLIC_BASE_PATH: prefix } };
              const { PDF_DOCUMENT_OPTIONS } = await import(
                `${prefix}/modules/pdfPreviewOptions.mjs`
              );
              const { getDocument, GlobalWorkerOptions } = await import(
                `${prefix}/pdf.mjs`
              );
              GlobalWorkerOptions.workerSrc = `${prefix}/pdf.worker.mjs`;
              const options = configured
                ? PDF_DOCUMENT_OPTIONS
                : { rangeChunkSize: 65536 };
              const pdf = await getDocument({
                url: `${prefix}/sample.pdf`,
                ...options,
              }).promise;
              const page = await pdf.getPage(1);
              const viewport = page.getViewport({ scale: 1.2 });
              const canvas = document.querySelector("canvas");
              canvas.width = Math.ceil(viewport.width);
              canvas.height = Math.ceil(viewport.height);
              const context = canvas.getContext("2d");
              await page.render({ canvasContext: context, viewport }).promise;
              const text = await page.getTextContent();
              const ink = (top, height) => {
                const pixels = context.getImageData(80, top, 560, height).data;
                let count = 0;
                for (let i = 0; i < pixels.length; i += 4) {
                  if (
                    pixels[i] < 180 &&
                    pixels[i + 1] < 180 &&
                    pixels[i + 2] < 180 &&
                    pixels[i + 3]
                  )
                    count++;
                }
                return count;
              };
              const fontResponse = await fetch(
                `${PDF_DOCUMENT_OPTIONS.standardFontDataUrl}LiberationSans-Regular.ttf`,
              );
              const result = {
                options: PDF_DOCUMENT_OPTIONS,
                text: text.items.map((item) => item.str).join(" "),
                items: text.items.length,
                titleInk: ink(50, 90),
                bodyInk: ink(220, 260),
                fontStatus: fontResponse.status,
              };
              await pdf.destroy();
              return result;
            },
            { prefix, configured },
          );
          assert.deepEqual(failures, []);
          assert.equal(observed.options.cMapUrl, `${prefix}/pdfjs/cmaps/`);
          assert.equal(
            observed.options.standardFontDataUrl,
            `${prefix}/pdfjs/standard_fonts/`,
          );
          assert.equal(observed.options.cMapPacked, true);
          assert.equal(observed.fontStatus, 200);
          if (configured) {
            assert.match(observed.text, /欢迎来到 Nexent 平台/);
            assert.match(observed.text, /这是.*自动生成的中文PDF示例文档/);
            assert.match(observed.text, /我都能为您提供便捷的支持/);
            assert.ok(
              observed.titleInk > 100,
              `Missing title ink: ${observed.titleInk}`,
            );
            assert.ok(
              observed.bodyInk > 500,
              `Missing body ink: ${observed.bodyInk}`,
            );
            assert.ok(
              requests.includes(`${prefix}/pdfjs/cmaps/UniGB-UCS2-H.bcmap`),
            );
            assert.equal(
              warnings.some((message) =>
                /translateFont failed|Error during font loading/.test(message),
              ),
              false,
            );
          } else {
            assert.equal(observed.items, 0);
            assert.equal(observed.titleInk, 0);
            assert.equal(observed.bodyInk, 0);
            assert.ok(warnings.some((message) => message.includes("cMapUrl")));
          }
          t.diagnostic(
            JSON.stringify({
              prefix,
              configured,
              items: observed.items,
              titleInk: observed.titleInk,
              bodyInk: observed.bodyInk,
            }),
          );
          if (process.env.RESULT_DIR && configured) {
            await page.locator("canvas").screenshot({
              path: path.join(
                process.env.RESULT_DIR,
                prefix ? "prefixed.png" : "root.png",
              ),
            });
          }
        } finally {
          await page.close();
        }
      }
    } finally {
      await new Promise((resolve) => server.close(resolve));
    }
  }
  assert.equal(digest(), before);
});
