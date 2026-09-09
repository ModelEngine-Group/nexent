# View Results and Annotations

After an evaluation task completes, open its details to review aggregate metrics, per-case results, and runtime information. You can also add human annotations to cases.

## View evaluation results

1. In **Agent Development > Agent Evaluation**, open the **Evaluation Tasks** tab.
2. Select **Details** for a task.

Task details include:

- **Overall score**: aggregate score across cases;
- **Passed / total cases**: pass status based on evaluator thresholds;
- **Average score per evaluator**: compare quality dimensions;
- **Score distribution**: inspect high-, medium-, and low-score cases;
- **Per-case results**: question, reference answer, actual output, score, reason, and status;
- **Run metadata**: agent, version, set, Judge model, creation time, end time, duration, and progress.

The case table supports **All / Passed / Failed**, viewing or sorting by one evaluator, filtering by session ID, and filtering by annotation value.

## AI analysis report

After a task completes, select **AI Analysis**. The Judge model analyzes aggregate statistics and selected failed cases, then returns:

- common problems or failure patterns;
- severity (high, medium, or low);
- an overall review;
- suggestions for prompt, knowledge-base, or tool configuration improvements.

The report is AI-generated for reference only and does not change the agent automatically. Select **Re-analyze** after editing cases or annotations.

## Export a report

On a completed task's details page, select **Download Report** to export a PDF containing task information, score summaries, and case results. The report follows the current interface language.

## Human annotations

Annotations record human judgments independently from automated scores. Use them for labels such as “grounded”, “problem type”, or free-text review notes. They do not change evaluator scores.

### Create annotation labels

In the **Annotation Labels** tab, select **Create Annotation Label** and choose a type:

| Type | Usage |
|------|-------|
| **Classification** | Configure multiple options, one per line, up to 20 options |
| **Boolean** | Record True / False |
| **Number** | Record a numeric value |
| **Text** | Record a free-text note |

Names are limited to 50 characters and descriptions to 200 characters. Enable the labels you need from a completed task's details page.

### Annotate a task

1. Open a completed task.
2. Select **Annotation Labels** and enable the labels to display.
3. Enter or edit values in the case table.
4. Filter by label value and review coverage and value distributions.

Disabling a label that already contains data asks for confirmation and deletes that label's data for the task. A label in use by an active task cannot be edited or deleted; wait for the task to finish or create a new label.
