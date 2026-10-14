import assert from "node:assert/strict";
import test from "node:test";

import {
  stripAnsiControlSequences,
  // @ts-expect-error -- Node's built-in TypeScript runner needs the extension.
} from "../lib/ansi.ts";

test("strips ANSI colours from a Jupyter traceback", () => {
  const traceback =
    "\u001b[31mHTTPError\u001b[39m: \u001b[32mHTTP Error 500\u001b[0m";

  assert.equal(
    stripAnsiControlSequences(traceback),
    "HTTPError: HTTP Error 500"
  );
});

test("strips OSC terminal metadata and preserves normal Unicode", () => {
  const output = "\u001b]0;kernel\u0007沙箱错误";

  assert.equal(stripAnsiControlSequences(output), "沙箱错误");
});
