// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { cpSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const frontendDirectory = fileURLToPath(new URL("../", import.meta.url));

export function preparePdfAssets({
  publicDirectory = path.join(frontendDirectory, "public"),
  packageDirectory = path.dirname(require.resolve("pdfjs-dist/package.json")),
} = {}) {
  for (const directory of ["cmaps", "standard_fonts"]) {
    cpSync(
      path.join(packageDirectory, directory),
      path.join(publicDirectory, "pdfjs", directory),
      { recursive: true, force: true }
    );
  }
}
