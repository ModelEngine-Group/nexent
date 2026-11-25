# Agent Evaluation

Agent Evaluation runs a batch of test questions against a selected agent version and scores the resulting answers with one or more evaluators. After a run finishes, Nexent provides aggregate metrics, per-case results, and an optional AI analysis report.

Use evaluation to:

- validate prompt, model, knowledge-base, or tool changes before release;
- run repeatable regression checks against a stable test set;
- inspect quality dimensions such as accuracy, completeness, safety, relevance, and execution health;
- add human annotations to failed or noteworthy cases.

## Open the Evaluation page

After signing in, select **Agent Evaluation** from the left navigation. You can also open an agent card on the **Agent Configuration** page and select **Evaluate** from its **More** menu. This entry is only available for agents with a published version, and the evaluation task list is filtered by that agent automatically.

The page contains four tabs:

| Tab | Purpose |
|-----|---------|
| **Runs** | Create evaluations and view task status and history |
| **Evaluators** | View built-in evaluators and manage custom evaluators |
| **Sets** | Upload, generate, and maintain test cases |
| **Annotation Labels** | Define labels for manual review |

If the entry is not visible, ask a tenant administrator to check your page permissions.

## Before you start

1. Configure at least one usable large language model in Model Management. It can be used as the **Judge model** and for AI generation.
2. Create an agent and publish at least one version. Evaluation runs a published version and does not evaluate an unsaved draft.
3. Prepare an evaluation set, or select **Evaluation without a set** when creating a task to let AI generate test questions from the agent configuration.
4. Prepare at least one published evaluator. A task must include at least one evaluator.

## Evaluation modes

| Item | Evaluation with a set | Evaluation without a set |
|------|------------------------|---------------------------|
| Question source | Existing evaluation set | AI-generated from agent configuration |
| Runs the agent | Yes | Yes |
| Reference answer | Depends on the set | Not available |
| Best for | Regression, release validation, and repeatable comparison | Quick exploration and smoke checks |
| Number of cases | Number of cases in the set | 1–50 questions (10 by default) |

### Evaluation with a set

The system sends each question in the selected set to the chosen agent version, then passes the actual answer and runtime information to the selected evaluators. Maintain reference answers in the set when evaluating answer accuracy, completeness, or factual accuracy.

### Evaluation without a set

The system reads the agent name, description, duties, constraints, and tools, then asks AI to generate test questions. It runs the agent against those questions and evaluates the results. Generated questions have no reference answers, so prefer evaluators such as Content Safety, Answer Relevance, Execution Success Rate, Tool Call Health, and Response Completeness.

This mode is useful for quickly checking an agent's basic behavior. For formal regression testing, curate questions and reference answers in an evaluation set first.

## Evaluation flow

An evaluation usually follows these steps:

1. On the **Runs** tab, select **Create Evaluation** and choose an evaluation mode.
2. Select an agent and a published version (the latest published version is used by default).
3. Configure the evaluation: select a Judge model; choose an evaluation set in with-set mode, or set the AI question count in no-set mode.
4. Select 1–5 published evaluators.
5. Select **Start Evaluation**. The agent runs and collects its answers and runtime information; evaluators score each case and generate the results and report.

The execution kernel is adapted automatically by the platform and requires no manual selection.

The pages below describe each step:

- [Create an Evaluation Task](./evaluation/create-task)
- [Manage Evaluation Sets](./evaluation/sets)
- [Configure Evaluators](./evaluation/evaluators)
- [View Results and Annotations](./evaluation/results)

## Limits

| Area | Current limit |
|------|---------------|
| Evaluation object | The current flow runs published Nexent agent versions |
| Evaluators per task | 5; only published evaluators can be selected |
| Evaluation sets | 50 per tenant |
| Cases per set | 2,000 |
| No-set questions | 1–50 per task, AI-generated from agent configuration |
| AI-generated set cases | 1–200 per request |
| Concurrent tasks | 5 active tasks per tenant; each tenant can retain up to 500 evaluation tasks |
| Historical data | Normally retained for about 30 days and may be cleaned by maintenance jobs |
| Multi-turn | Up to 10 turns per session during one run |
| Custom code | Restricted pure Python; no file, network, system-command, or arbitrary-module access |
| Evaluator content length | LLM prompt up to 5,000 characters; Code evaluator code up to 20,000 characters |
| Annotation labels | Up to 500 annotation labels in total; up to 5 annotation values per case |
