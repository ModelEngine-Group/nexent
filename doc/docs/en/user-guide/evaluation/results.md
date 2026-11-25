# View Results and Annotations

After an evaluation task completes, open its details to review aggregate metrics, per-case results, and runtime information. You can also add human annotations to cases.

## View evaluation results

1. In **Agent Evaluation**, open the **Runs** tab.
2. Select the details icon in the actions column of a task.

Task details include:

- **Header actions**: completed tasks provide **Annotation Labels**, **AI Analysis** (which becomes **Re-analyze** after a report is generated), and **Download Report**; failed tasks display the failure reason;
- **Overall score**: aggregate score across cases, together with the passed / total count (pass status based on evaluator thresholds);
- **Average score per evaluator**: a polar chart comparing quality dimensions;
- **Score distribution**: a histogram of high-, medium-, and low-score cases;
- **Per-case results**: question, reference answer, actual output, score, reason, and status;
- **Run metadata**: agent, version, set (shown as a "No Set" tag in no-set mode), Judge model, creation time, end time, duration, and progress.

The case table supports:

- switching between the **All / Passed / Failed** tabs;
- selecting one evaluator from the "per evaluator" dropdown to view or sort its scores;
- filtering multi-turn cases by session ID;
- filtering cases by annotation value;
- long text is truncated by default; hover to see the full content and per-evaluator scores.

## AI analysis report

After a task completes, select **AI Analysis**. The Judge model analyzes aggregate statistics and selected failed cases, then returns:

- common problems or failure patterns, tagged with **high / medium / low** severity and a fix suggestion;
- an overall review;
- suggestions for prompt, knowledge-base, or tool configuration improvements.

The report is AI-generated for reference only and does not change the agent automatically. Select **Re-analyze** after editing cases or annotations.

## Export a report

On a completed task's details page, select **Download Report** to export a PDF containing task information, score summaries, case results, and annotation statistics (coverage and option distribution for each label). The report follows the current interface language.

## Human annotations

Annotations record human judgments independently from automated scores. Use them for labels such as “grounded”, “problem type”, or free-text review notes. They do not change evaluator scores.

### Create annotation labels

In the **Annotation Labels** tab, select **Create Annotation Label** and choose a type:

| Type | Usage |
|------|-------|
| **Classification** | Configure multiple options, one per line, up to 20 options |
| **Boolean** | Record True / False; the True / False options are generated automatically |
| **Number** | Record a numeric value |
| **Text** | Record a free-text note |

Names are limited to 50 characters and descriptions to 200 characters. Enable the labels you need from a completed task's details page.

### Annotate a task

1. Open a completed task and select **Annotation Labels** in the top-right corner.
2. Enable the labels to use in the dialog; enabled labels appear as extra columns in the case table.
3. Enter or edit annotation values directly in those columns: classification labels use a dropdown, number labels take a numeric input, and text labels take a text input; changes save immediately.
4. Filter cases from the annotation column headers; the annotation statistics cards in the details page show each label's coverage and option distribution.

Disabling a label that already contains data asks for confirmation and deletes that label's data for the task. A label in use by an active task cannot be edited or deleted; wait for the task to finish or create a new label.
