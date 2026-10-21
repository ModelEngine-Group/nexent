# Tag definition search matching and result presentation

Observed on 2026-10-21 in the tag management dialog opened from resource management. No separate nexent-doc
checkout is available, and the inspected formal Cases contain no contract for the tag definition table, so this
is a lightweight bug design rather than a new resource-management SPEC.

## Scope and final behavior

The definition table searches the text a user can see and type: the localized definition name that the table
renders, the raw definition key stored by the backend, and the display and normalized text of the values. A
name or key hit is already visible in the collapsed row, so that row stays collapsed and shows the matched
fragment highlighted. A row reached only through a value opens, lists the matching values only, and highlights
them. Clearing the search restores the rows and value lists the user had before, and every search keeps the
management dialog at a constant height while it filters. Value filtering inside an opened row, manual collapse,
pagination, mutations and permissions are unchanged, and no backend route or payload changes.

## Root cause and implementation

frontend/lib/systemTagLabels.ts resolved the searchable text of a definition from the raw identifier only and
compared it against the untranslated value column, so a keyword such as a translated fragment never matched a
row that displays a localized name. The match helpers now reuse the same display-name helpers the table renders
with, and additionally cover every value regardless of status so that a row visible in the expanded table can
be found by its own values.

getTagSearchMatches returns per-definition match details instead of a flat id list, which lets
frontend/components/tag/TagDefinitionManagementPanel.tsx keep the presentation decision with the caller: only
value-only hits set the auto-expanded keys, tracked apart from the user's own expansions so a new keyword
retracts only what it opened. Row highlighting is rendered by the new
frontend/components/common/HighlightedText.tsx.

The dialog resizes because an antd table body is only as tall as its current rows, and the new stableTableHeight
prop pins the body to the height scroll.y already requests. Only the dialog passes the switch; the panel embedded
in resource management keeps its natural height.

## Acceptance and evidence

| Requirement | Intended proof | Current evidence |
| --- | --- | --- |
| A definition is found by its localized name, raw key or a value | Component regression | Implemented; 14 component tests executed and passing |
| A name or key hit stays collapsed and is highlighted | Component regression | Implemented; executed |
| A value-only hit opens the row and lists the matched values | Component regression | Implemented; executed |
| Clearing the search restores rows and full value lists | Component regression | Implemented; executed |
| The management dialog keeps its height during a search | Component assertion on the pinned table body | Implemented; jsdom cannot measure the real layout |
| Firefox rendering of the expanded-row icon | Browser visual check | Not a regression from this change; upstream antd expander with Firefox sub-pixel line rendering |

Verification: frontend/tests/component/tagDefinitionSearch.test.tsx passes together with the neighbouring
tagLibraryManagement, resourceTagManagement and resourceTagFilter tests; targeted ESLint, Prettier, copyright
and diff whitespace checks pass. Type checking is blocked only by pre-existing unrelated diagnostics in the
checkout. No formal D1-D5 Case is claimed for this feature, and no backend, API or persistence contract changed.
