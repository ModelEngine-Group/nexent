# Manage Evaluation Sets

An evaluation set is a collection of test cases used to drive an evaluation. Every case must contain a question. A reference answer is optional at the data level but is important for Answer Accuracy, Answer Completeness, and Factual Accuracy.

## Import an Excel file

1. In **Agent Development > Agent Evaluation**, open the **Evaluation Sets** tab.
2. Select **Upload**, enter a set name and optional description.
3. Upload an `.xlsx` or `.xls` file. You can also select **Download Template** before filling in the data.

The following column names are supported. Chinese and English headers are accepted:

| Field | Chinese header | Required | Description |
|-------|----------------|:--------:|-------------|
| `session_id` | 会话ID | No | Same ID groups turns in one conversation |
| `request_id` | 请求顺序 | No | Turn order within a conversation, starting at 1 |
| `query` | 问题 | **Yes** | User input sent to the agent |
| `answer` | 答案 | No | Reference answer; `reference_output` and `expected_output` are also accepted |

Leave session fields empty for single-turn cases. For multi-turn cases, keep turn numbers consecutive. One evaluation run processes at most 10 turns per session.

## Generate a set with AI

1. In the **Evaluation Sets** tab, select **AI Generate Evaluation Set**.
2. Enter a scene description and select a generation model.
3. Choose whether to append cases to an existing set or enter a name for a new set.
4. Set the generation count (1–200) and start generation.

Optional context includes:

- a knowledge base, so the system can retrieve relevant content first;
- an agent, whose configuration, tools, skills, and sub-agents provide context;
- one `.docx` reference document.

Generation runs asynchronously. The set shows **Generating**, **Ready**, or **Failed**. Open the set after generation to review and edit the cases.

> Review AI-generated questions and reference answers before using them as a formal benchmark.

## Review and maintain cases

Open **View** for a set to search by question, add a case, edit its question, answer, session ID, or turn order, delete individual or selected cases, and export the set as Excel.

The system restricts changes that could invalidate a set while it is referenced by an active evaluation task. Copy or export the set before maintaining a long-lived benchmark if necessary.

## Data limits

| Area | Current limit |
|------|---------------|
| File format | `.xlsx` and `.xls` only |
| Upload size | 20 MB per file |
| Evaluation sets | 50 per tenant |
| Cases | 2,000 per set |
| Question length | 2,000 characters |
| Reference-answer length | 5,000 characters |
| Set name | 2–64 characters |
| Multi-turn | Up to 10 turns per session during one run |
