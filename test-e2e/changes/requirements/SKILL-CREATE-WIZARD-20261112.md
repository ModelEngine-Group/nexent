# Resource repository skill creation wizard — 2026-11-12

## Scope and reference

User-provided screenshots define the manual/import creation layout. The owning
entry is `frontend/components/repository/skill/my-skill.tsx`. Existing edit and
non-repository `SkillBuildModal` flows remain in place; the new wizard is used
only for creation in the unified resource repository. Workbench creation remains
available through its existing entry. No backend endpoints, SQL or dependency
declarations are changed.

The sibling SPEC repository and authoritative UI document were unavailable in
this checkout during the preceding repository layout work. This record captures
the current change, observable acceptance and verification limits, without
inventing a historical SPEC or formal Case IDs.

## Acceptance and implementation

- Configure parameters first, then select accessible user groups and their
  existing EDIT/READ_ONLY/PRIVATE permission. Name and description are required;
  description is capped at 1000 characters. Advancing does not create a resource.
- Manual creation starts with SKILL.md and supports nested text files, editing,
  preview, copy, download and saving changes to the draft. New paths must be
  relative, must not traverse directories and must not conflict with existing
  file/directory paths, including case-insensitive SKILL.md collisions.
- Import accepts Markdown/ZIP, parses locally and populates editable metadata
  and files. Missing/unreadable SKILL.md, malformed YAML/ZIP and unsupported
  input show an error. Frontmatter is separated from the editable body so saving
  does not duplicate it. Text decoding retains the prior UTF-8/GB18030/Big5 support.
- ZIP submission sends the original file at final confirmation and then updates
  metadata/readable drafts. Binary assets are not decoded or replaced by empty
  text. The existing backend/SDK save contract writes submitted extra files
  without deleting unsubmitted files (`SkillManager.save_skill`). Actual live
  storage retention is not established by frontend mocks.
- Tags use existing active library values and canonical assignments after the
  resource ID is known; legacy flat tags are not manufactured. Imported labels
  are matched to active values, single-select definitions are normalized and
  unknown labels are reported. The user can review/change the selection.
- Partial failures after creation retain the created ID and retry its metadata
  or tag configuration instead of creating a duplicate. A success response with
  no usable ID blocks resubmission and asks the user to refresh the list.
- Saving disables duplicate submission and dismissal. Cancel before confirmation
  performs no creation. Switching methods with a dirty draft asks before clearing
  it, and stale parse results cannot overwrite a later choice or closed dialog.

## Test responsibilities and limits

### Group selection table follow-up

The second-step screenshot is implemented with the shared `StandardTable`:
permission selector first, followed by real group name, description and member
count columns. Missing member counts are shown as a dash rather than invented
zeroes. The wizard continues to load the existing all-groups query and filters
it by `getAccessibleGroupIds`; the table paginates the resulting accessible list
locally in groups of 10, so totals do not leak inaccessible groups.

Form-controlled IDs persist between pages. Header selection affects only the
current page, and selections on other pages are retained when that page is
cleared. Saving disables checkboxes and page changes. Loading/error states are
visible; failed group queries offer retry and block final creation confirmation.
Existing default selections and EDIT/READ_ONLY/PRIVATE semantics are unchanged.
The dialog preserves the reference's open space below the table and fixed footer,
within the viewport height; narrow tables scroll horizontally.

Added `skillGroupSelection.test.tsx` covers real descriptions/zero counts,
cross-page selection and page-only select-all/clear, disabled selection and
empty/error/retry states. `skillCreateModal.test.tsx` now also checks that only
accessible groups are displayed and that existing default IDs reach creation.
The isolated run passed 9 tests across these two files; no live group data or
backend authorization behavior was changed or mutated by the tests. Python UT
remains inapplicable to the frontend-only adjustment. Full type/build and browser
visual/journey acceptance remain unverified; no deployment was performed.

Traditional Python UT is not applicable: no Python behavior changes. Frontend UT
is added under `frontend/tests/component/` and remains separate from formal D1–D5.
No formal Case was removed, relabeled or added to meet a stage quota.

Relevant selectors:

- `skillCreationDraft.test.tsx`: Markdown metadata/body, nested ZIP/binary status,
  unsupported/corrupt/missing-primary inputs and valid/invalid relative paths.
- `skillCreationFiles.test.tsx`: edit/save/preview and invalid/new nested paths.
- `skillCreateModal.test.tsx`: required-field gate, no mutation before final
  confirmation, canonical tag retry against the same ID, original ZIP submission,
  missing-ID retry guard and cancellation of a dirty method switch.

These tests use real local ZIP/YAML parsing and Ant Design forms with mocked
network boundaries. The isolated harness uses Vitest 4.1.12, React 19.2.3 and
Ant Design 6.3.0; it is not the repository's full dependency set. Full type/build,
browser/D4 visual/journey and real backend creation/storage/permission acceptance
remain unverified because this task changes code without deploying the result.

Copyright, Prettier parsing/formatting, translation key checks and
`git diff --check` are the applicable source checks. Final targeted test outcome
is recorded after execution; passing unit tests do not imply the unverified
higher-boundary acceptance above.

## Execution evidence

- The three targeted files passed after the final relevant reruns: 19 tests total
  (12 parser/path tests, 2 editor tests and 5 wizard tests). The final dirty-switch
  check waits for the real Ant Design modal animation before asserting visibility.
- Command in `/tmp/skill-detail-regression` with `NODE_ENV=test`:
  `node node_modules/vitest/vitest.mjs run tests/component/skillCreationDraft.test.tsx tests/component/skillCreateModal.test.tsx tests/component/skillCreationFiles.test.tsx`;
  the wizard file was rerun after its final animation-wait adjustment.
- Copyright validation for all seven changed/new source/test files passed;
  Prettier parsing/formatting and source whitespace checks passed. English/Chinese
  creation keys were checked against the component references.
- Tests used mocked create/update/tag APIs and in-memory ZIPs. No real skill was
  created and no deployment was performed. Full build/type and real browser/API
  acceptance remain unverified.
