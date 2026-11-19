// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

/**
 * AIDP-ONTOLOGY-D4-001 — browser journey placeholder bound to the temporary UI verification.
 *
 * The executable journey is maintained with the local Playwright screenshot
 * harness during the temporary-UI phase; the formal queue wrapper is added
 * when the temporary UI is replaced by the official UCD.
 */
import { test } from "playwright/test";

test("AIDP-ONTOLOGY-D4-001", async () => {
  test.fixme(true, "Temporary UI journey is verified by the local screenshot harness");
});
