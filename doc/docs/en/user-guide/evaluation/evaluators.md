# Configure Evaluators

An evaluator defines what to measure and how to score it. A task can select up to five published evaluators. Each case stores the score and reason for every selected evaluator.

## Built-in evaluators

In **Agent Development > Agent Evaluation**, open **Evaluators > Built-in Evaluators** to view and use these evaluators:

| Evaluator | Type | Main purpose | Reference answer |
|-----------|------|--------------|:----------------:|
| Answer Accuracy | LLM | Compare key points with the reference answer | Yes |
| Answer Completeness | LLM | Check for missing key information | Yes |
| Content Safety | LLM | Check harmful, non-compliant, biased, or leaked content | No |
| Format Validation | Code | Check output format (the built-in rule validates JSON) | No |
| Answer Relevance | LLM | Check whether the answer addresses the question | No |
| Factual Accuracy | LLM | Check fabricated or unverifiable claims | Recommended |
| Execution Success Rate | LLM | Judge whether execution completed successfully | No |
| Tool Call Health | LLM | Judge tool-call errors, retries, and success | No |
| Token Efficiency | LLM | Judge whether token usage is reasonable | No |
| Response Completeness | LLM | Check truncation or early termination | No |
| MCP Connection Health | LLM | Check MCP connection and authentication errors | No |

LLM evaluators use the Judge model to return a score and reason. Code evaluators apply deterministic Python rules. LLM scores are probabilistic and should be interpreted together with failed cases and repeated runs.

## Create a custom evaluator

In **Evaluators > Custom Evaluators**, select **Create Evaluator**. You can use AI generation or enter the configuration manually.

### AI Generate

Describe the desired check in natural language, such as “Check that the customer-service answer is polite, complete, and does not fabricate facts.” Select a generation model and optionally a target agent, then select **AI Generate**. Nexent fills in the name, description, type, prompt or code, and score range.

Generated content only fills the editor and is not published automatically. Review the evaluation dimension, inputs, score rules, and prompt before saving.

### Manual creation

Enter a name, description, judgment type, and score rules:

- **LLM**: write a prompt for the Judge model;
- **Code**: write a pure Python function for format, keyword, numeric, or other deterministic checks.

The lower score bound must be below the upper bound, the upper bound must not exceed 100, and the pass threshold must be within the range. Built-in evaluators normally use 0–1 scores and a 0.5 threshold.

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
- Editing a published custom evaluator creates a new draft version; the previous published version remains in history.
- Version history supports viewing, restoring, and deleting historical versions, subject to active-task references.
- Custom evaluators can be exported to JSON and imported elsewhere. Import skips duplicate name-and-type pairs.
