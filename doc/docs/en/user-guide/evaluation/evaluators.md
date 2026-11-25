# Configure Evaluators

An evaluator defines what to measure and how to score it. A task can select up to five published evaluators. Each case stores the score and reason for every selected evaluator.

## Built-in evaluators

In **Agent Evaluation**, open the **Evaluators** tab and switch between **Built-in Evaluators** and **Custom Evaluators** using the sub-tabs. Built-in evaluators appear as cards showing the name, judgment type (LLM / Code), and published status:

| Evaluator | Type | Main purpose | Reference answer |
|-----------|------|--------------|:----------------:|
| Answer Accuracy | LLM | Compare key points with the reference answer | Yes |
| Answer Completeness | LLM | Check for missing key information | Yes |
| Content Safety | LLM | Check harmful, non-compliant, biased, or leaked content | No |
| Format Validation | Code | Check output format (the built-in rule validates JSON) | No |
| Answer Relevance | LLM | Check whether the answer addresses the question | No |
| Factual Accuracy | LLM | Check fabricated or unverifiable claims | Required |
| Execution Success Rate | LLM | Judge whether execution completed successfully | No |
| Tool Call Health | LLM | Judge tool-call errors, retries, and success | No |
| Token Efficiency | LLM | Judge whether token usage is reasonable | No |
| Response Completeness | LLM | Check truncation or early termination | No |
| MCP Connection Health | LLM | Check MCP connection and authentication errors | No |

LLM evaluators use the Judge model to return a score and reason. Code evaluators apply deterministic Python rules. LLM scores are probabilistic and should be interpreted together with failed cases and repeated runs.

No-set evaluation has no reference answers, so evaluators that require one cannot be selected in that mode.

## Create a custom evaluator

On the **Evaluators > Custom Evaluators** sub-tab, select **Create Evaluator** in the top-right corner. A drawer slides out with the **AI Generate** and **Evaluator Configuration** sections.

### AI Generate

In the **AI Generate** card, describe the desired check in natural language (up to 500 characters), such as “Check that the customer-service answer is polite, complete, and does not fabricate facts.” Select a generation model and optionally a target agent, then select **AI Generate**. The generated name, description, type, prompt or code, and score range are filled into the form below.

Generated content only fills the editor and is not published automatically. Review the evaluation dimension, inputs, score rules, and prompt before saving.

### Evaluator configuration

Fill in or adjust the following in the **Evaluator Configuration** card:

- **Name** (up to 50 characters) and **description** (up to 200 characters);
- **Judgment type**: **LLM** writes a prompt (up to 5,000 characters) that the Judge model uses to return a score and reason; **Code** writes a pure Python function (up to 20,000 characters) that defines `evaluate(query, expected, actual)` for format, keyword, numeric, or other deterministic checks;
- **Score range and pass threshold**: the lower bound must be below the upper bound, the upper bound must not exceed 100, and the pass threshold must be within the range. Built-in evaluators normally use 0–1 scores and a 0.5 threshold.

Select **Save** to store the evaluator as a draft.

## LLM prompt placeholders

Custom LLM prompts can use:

| Placeholder | Replaced with |
|-------------|---------------|
| `{{query}}` | User question |
| `{{expected}}` | Reference answer; empty in no-set mode |
| `{{actual}}` | Agent's actual answer |
| `{{runtime_stats}}` | Runtime statistics for process-quality checks |

Ask the Judge model to return a JSON object, for example:

```json
{"score": 0.8, "reason": "The response covers the main points but misses one detail."}
```

An empty, non-JSON, or invalid score response is recorded as 0 with an explanatory reason.

## Code evaluator safety boundary

A Code evaluator must define `evaluate` and return `score` and `reason`:

```python
def evaluate(query, expected, actual, runtime_events):
    if actual.strip().startswith("{"):
        return {"score": 1.0, "reason": "Output looks like JSON"}
    return {"score": 0.0, "reason": "Output is not JSON-like"}
```

Code is syntax-checked, statically scanned, executed with a restricted built-in set, and checked for the required function signature. Imports outside the allowlist, file access, network I/O, system commands, and object-introspection escape paths are blocked. Use Code evaluators for pure computation and string processing only.

## Drafts, publishing, and versions

- New and edited custom evaluators are **Draft** and cannot be selected for a task.
- Select **Publish** before using one in an evaluation task.
- Built-in evaluators are published and cannot be edited or deleted.
- When editing a published custom evaluator, the name, description, score range, and threshold can be changed, and the prompt of an LLM evaluator can also be changed; the judgment type and Code evaluator code cannot be changed. Saving creates a new draft version; the previous published version remains in history.
- **Version History** on an evaluator card shows each version's type, status, score range, and prompt summary, and offers **Restore** and **Delete** for non-current versions, subject to active-task references.
- Custom evaluators can be exported to JSON (select the entries to export) and imported elsewhere with the import button in the top-right corner of the Evaluators tab. Import skips duplicate name-and-type pairs.
