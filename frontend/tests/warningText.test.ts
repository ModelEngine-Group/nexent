import assert from "node:assert/strict";
import test from "node:test";

import {
  formatWarningText,
  // @ts-expect-error -- Node's built-in TypeScript runner needs the extension.
} from "../lib/warningText.ts";

test("shows only the final exception from a nested traceback", () => {
  const warning = [
    "HTTPError Traceback (most recent call last)",
    "File /usr/local/lib/python3.11/urllib/request.py, line 66",
    "HTTPError: HTTP Error 500: Internal Server Error",
    "The above exception was the direct cause of the following exception:",
    "RuntimeError: Local tool bridge request failed: Sandbox script failed. Repair the script and rerun run_skill_script before continuing: timeout: failed to run command 'node': No such file or directory",
  ].join("\n");

  assert.equal(
    formatWarningText(warning),
    "RuntimeError: Local tool bridge request failed: Sandbox script failed. Repair the script and rerun run_skill_script before continuing: timeout: failed to run command 'node': No such file or directory"
  );
});

test("keeps concise warnings unchanged apart from whitespace normalization", () => {
  assert.equal(
    formatWarningText("Sandbox kernel channel failed:\nlease replaced"),
    "Sandbox kernel channel failed: lease replaced"
  );
});

test("keeps the complete final exception for CSS line clamping", () => {
  const message = `RuntimeError: ${"x".repeat(600)}`;

  assert.equal(formatWarningText(message), message);
});
