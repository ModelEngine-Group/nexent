# Report investigation contacts

`report-ownership.yaml` is a repository-owned routing map, validated by its adjacent Schema. It does not change case status, acceptance, execution selection or notification recipients. Names prefixed with `@` are display text, not automatically resolved Feishu mentions.

Reports expose two independent fields:

- **Git last modifier**: the author and commit of the latest change at the pinned batch revision affecting the Case's `case.yaml`, `execution.yaml` or primary script. It is not the original designer, PR merger or proven bug author. Shared helper changes are not attributed to every Case. Local uncommitted Case changes are marked explicitly; missing/shallow history can yield Unknown or an import/squash author rather than the original author.
- **Responsibility contact**: the functional area and contact from the maintained map. This routes investigation; failure cause must still be established separately.

Precedence is Case override, Feature override, exact leading Feature description category, then explicit Feature-ID patterns. Failure messages, incidental keywords, Case counts and model inference never determine routing. No match stays Unassigned; multiple matches stay ambiguous. Cross-area rules can be clarified with a specific Case override rather than broadening a keyword match. Update contacts/rules here instead of editing hundreds of Case contracts; new domains must satisfy the existing Schema and override values must reference a defined domain.

The batch snapshots author, commit, path, contact and routing basis in `report-ownership.json` and includes them in journal/checkpoint results. Historical report rendering uses saved metadata, not current Git or current contacts. Execution plan bindings remain unchanged so attribution does not invalidate same-version resume checks. Invalid configuration or unavailable history is recorded as attribution warnings, never a guessed person or changed test result.

The Markdown report replaces the empty legacy Owner display with Git last modifier and responsibility contact. Existing complete-run D6 notification behavior is unchanged; no independent message is sent by routing. Do not modify a running batch's repository/configuration to retrofit these fields.
