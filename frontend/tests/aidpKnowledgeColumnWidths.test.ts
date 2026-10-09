import assert from "node:assert/strict";
import test from "node:test";
import {
  fitAidpColumnWidths,
  resizeAidpColumnPair,
  // @ts-expect-error -- Node requires the extension for this standalone test.
} from "../lib/aidpKnowledgeColumnWidths.ts";

test("dragging either way redistributes only the two boundary columns", () => {
  const widths = { name: 240, type: 120, description: 300 };
  assert.deepEqual(resizeAidpColumnPair(widths, "name", "type", 40), {
    name: 280,
    type: 80,
    description: 300,
  });
  assert.deepEqual(resizeAidpColumnPair(widths, "name", "type", -40), {
    name: 200,
    type: 160,
    description: 300,
  });
  assert.equal(widths.name, 240);
});

test("dragging stops at 64px on either side, without squeezing a third column", () => {
  const widths = { name: 240, type: 120, description: 300 };
  assert.deepEqual(resizeAidpColumnPair(widths, "name", "type", 1000), {
    name: 296,
    type: 64,
    description: 300,
  });
  assert.deepEqual(resizeAidpColumnPair(widths, "name", "type", -1000), {
    name: 64,
    type: 296,
    description: 300,
  });
});

test("container resizing preserves user proportions before hitting the minimum", () => {
  const keys = ["name", "type", "actions"] as const;
  const weights = { name: 300, type: 200, actions: 100 };
  assert.deepEqual(fitAidpColumnWidths(keys, weights, 1200), {
    name: 600,
    type: 400,
    actions: 200,
  });
  assert.deepEqual(fitAidpColumnWidths(keys, weights, 600), weights);
});

test("minimum widths are frozen and the remaining space is redistributed", () => {
  const keys = ["name", "type", "actions"] as const;
  const result = fitAidpColumnWidths(
    keys,
    { name: 500, type: 100, actions: 50 },
    300
  );
  assert.deepEqual(result, { name: 172, type: 64, actions: 64 });
  assert.equal(
    Object.values(result).reduce((sum, width) => sum + width, 0),
    300
  );
});

test("narrow containers overflow horizontally instead of reducing the minimum", () => {
  assert.deepEqual(
    fitAidpColumnWidths(
      ["name", "type", "actions"],
      {
        name: 300,
        type: 200,
        actions: 100,
      },
      100
    ),
    { name: 64, type: 64, actions: 64 }
  );
});

test("hidden columns are excluded from layout without losing their preferences", () => {
  const weights = { name: 300, type: 200, actions: 100 };
  assert.deepEqual(fitAidpColumnWidths(["name", "actions"], weights, 800), {
    name: 600,
    actions: 200,
  });
  assert.deepEqual(
    fitAidpColumnWidths(["name", "type", "actions"], weights, 600),
    weights
  );
});
