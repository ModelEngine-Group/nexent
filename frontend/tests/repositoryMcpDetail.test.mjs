import assert from "node:assert/strict";
import test from "node:test";

import {
  resolveRepositoryMcpToolCount,
  resolveRepositoryMcpTools,
} from "../lib/repositoryMcpDetail.ts";

test("keeps published tool names and descriptions for the detail list", () => {
  const service = {
    registryJson: {
      tools: [
        "search",
        { name: "summarize", description: "Summarize a document" },
        { description: "Missing name" },
      ],
    },
  };

  assert.deepEqual(resolveRepositoryMcpTools(service), [
    { name: "search", description: "" },
    { name: "summarize", description: "Summarize a document" },
  ]);
  assert.equal(resolveRepositoryMcpToolCount(service), 3);
});

test("uses published tool names when full tool data is unavailable", () => {
  const service = { registryJson: { _toolNames: ["lookup", "fetch"] } };

  assert.deepEqual(resolveRepositoryMcpTools(service), [
    { name: "lookup", description: "" },
    { name: "fetch", description: "" },
  ]);
  assert.equal(resolveRepositoryMcpToolCount(service), 2);
});
