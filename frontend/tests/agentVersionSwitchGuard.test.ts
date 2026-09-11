import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const pagePath = new URL("../app/[locale]/agents/page.tsx", import.meta.url);

test("skips version detail loading while switching or when no version exists", async () => {
  const page = await readFile(pagePath, "utf8");

  assert.match(
    page,
    /const shouldFetchVersionDetail\s*=\s*!isRequestedAgentLoading\s*&&\s*total\s*>\s*0\s*;/
  );
  assert.match(
    page,
    /useAgentVersionDetail\(\s*currentAgentId,\s*agentInfo\?\.current_version_no\s*\?\?\s*null,\s*shouldFetchVersionDetail\s*\)/
  );
});
