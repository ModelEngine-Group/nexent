import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const selectorPath = new URL(
  "../app/[locale]/agents/agent-selector-header.tsx",
  import.meta.url
);

test("uses URL synchronization as the only selector loading path", async () => {
  const selector = await readFile(selectorPath, "utf8");
  const selectionStart = selector.indexOf("const handleSelectAgent = useCallback");
  const selectionEnd = selector.indexOf("  useEffect(() =>", selectionStart);
  const selectionHandler = selector.slice(selectionStart, selectionEnd);

  assert.doesNotMatch(selectionHandler, /searchAgentInfo\(/);
  assert.doesNotMatch(selectionHandler, /initialize\(/);
  assert.match(
    selector,
    /requestedAgentIdRef\.current\s*=\s*parsedAgentId;\s*if\s*\(currentAgentId\s*!==\s*parsedAgentId\)\s*\{\s*void loadAgent\(parsedAgentId\);\s*\}/
  );
});
