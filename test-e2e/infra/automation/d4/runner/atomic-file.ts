// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { mkdirSync, renameSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";

export function atomicJson(path: string, value: object): void {
  mkdirSync(dirname(path), { recursive: true });
  const temporary = `${path}.next`;
  writeFileSync(temporary, `${JSON.stringify(value, null, 2)}\n`, "utf8");
  for (let attempt = 0; ; attempt++) {
    try {
      renameSync(temporary, path);
      return;
    } catch (error) {
      const code = (error as NodeJS.ErrnoException).code;
      // Windows readers/indexers can briefly deny replace/delete sharing.
      // Keep the old complete file; never unlink it or hide persistent errors.
      if (process.platform !== "win32" || !["EPERM", "EBUSY", "EACCES"].includes(code ?? "") || attempt >= 8) throw error;
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 25);
    }
  }
}
