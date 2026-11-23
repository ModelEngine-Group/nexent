import assert from "node:assert/strict";
import test from "node:test";

const evaluationTaskFiltersPath = "../lib/evaluationTaskFilters.ts";

const loadEvaluationTaskFilters = () => import(evaluationTaskFiltersPath);

test("FE-COMP-ETL-002-S1 defaults to an unfiltered evaluation-task query", async () => {
  const { buildEvaluationTaskQuery } = await loadEvaluationTaskFilters();
  assert.equal(buildEvaluationTaskQuery([]), "limit=0");
});

test("FE-COMP-ETL-002-S2 serializes selected agents as one JSON list", async () => {
  const { buildEvaluationTaskQuery } = await loadEvaluationTaskFilters();
  assert.equal(
    buildEvaluationTaskQuery([7, 9]),
    "limit=0&agent_ids=%5B7%2C9%5D"
  );
});

test("FE-COMP-ETL-002-S3 parses valid lists and rejects malformed values", async () => {
  const { parseEvaluationTaskAgentIds } = await loadEvaluationTaskFilters();
  assert.deepEqual(parseEvaluationTaskAgentIds("[7,9,7]"), [7, 9]);
  assert.deepEqual(parseEvaluationTaskAgentIds('[7,"nine"]'), []);
  assert.deepEqual(parseEvaluationTaskAgentIds("not-json"), []);
});

test("FE-COMP-ETL-002-S4 preserves the filter when deciding whether to show a new task", async () => {
  const { shouldShowCreatedEvaluationTask } = await loadEvaluationTaskFilters();
  assert.equal(shouldShowCreatedEvaluationTask([], 7), true);
  assert.equal(shouldShowCreatedEvaluationTask([7, 9], 9), true);
  assert.equal(shouldShowCreatedEvaluationTask([7, 9], 10), false);
});
