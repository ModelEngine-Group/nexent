# Skill repository layout — 2026-11-12

## Scope and acceptance

Reference: the user-provided resource repository / all skills screenshot.
Entry point: `frontend/components/repository/skill/components/RepositoryView.tsx`.
The sibling document repository and `../docs/前端ui.md` are unavailable in this checkout;
the screenshot and existing component references define this presentation-only adjustment.

- All-skills cards fill three equal columns at container widths of at least 1200px,
  two at 720–1199px, and one below 720px. Other resource grids retain their layout.
- The card header centers its icon and action; tags occupy one clipped row.
  Descriptions use two lines, followed by the author label and installation count.
- Card mode omits extra sort/layout controls and publication timestamps to match
  the reference. Existing search, tag filtering, tabs and pagination remain.
- Installation, copy/uninstall menus, loading guards, permission checks, error and
  empty states retain their existing contracts. No sample data is introduced.
- The permission-controlled skill take-down menu is aligned to the bottom-right
  of the card's metadata row. Installation stays in the header, and list view
  retains its existing actions. Take-down callbacks and confirmations are unchanged.
- Skill icons distinguish green documents/files/spreadsheets, pink presentations,
  and blue generic skills. Recognized icon identifiers (`file-text`, `presentation`,
  `layers`) override inference; otherwise tags take precedence over name tokens.
  Unknown and empty metadata safely falls back to blue. Descriptions and opaque
  numeric category IDs are not used as classification evidence.

## Verification responsibilities

### Skill listing application follow-up

Reference: the user's listing-application screenshot (2026-11-12).
`MineApplyListingModal` now uses the shared standard modal with a skill-specific
title, the existing review explanation, an optional note, a 1000-character
counter/limit and cancel/confirm footer actions. Agent listing strings and APIs
are unchanged. Existing icon/tag payload mapping and whitespace trimming remain.

Submission disables editing/dismissal and duplicate confirmation. Failures keep
the modal and typed note available for retry; successful submission closes it.
The skill page previously swallowed rejected listing mutations, making them look
successful to the modal. Its callback now propagates the error after the existing
permission-specific/general notification, and the modal renders an inline failure
state rather than closing or leaving an unhandled promise rejection.

Frontend UT: `skillApplyListingModal.test.tsx`, 5 tests passed in the isolated
Vitest 4.1.12 harness with real shared modal/Ant Design controls and mocked submit
callbacks. Coverage includes empty optional notes, the 1000/1001 boundary,
trimmed payloads, failure/retry, duplicate/dismissal guards and a missing skill.
No real listing was submitted. No Python changes apply; no formal Case is added
as a quota or claimed executed. Full type/build and browser/live review workflow
acceptance remain unverified, and deployment remains outside this code-only task.

### Read-only skill detail follow-up

Reference: the user's skill-detail modal screenshot (2026-11-12). Repository
skill listings and installed skills use the same read-only metadata/file-browser
layout. Editing/generation panels keep their existing `SkillDraftPanel` path.

- Display name, localized source, tags and description as plain metadata; use
  cancel/confirm/close to dismiss the read-only dialog without saving anything.
- Build nested file directories with full-path keys, preserve directory ancestry
  during case-insensitive search, default to SKILL.md and allow switching files.
- Render Markdown through the existing shared renderer, retain skill directive
  navigation and expanded preview, and display other readable files as escaped
  preformatted text. The new repository browser does not provide code syntax
  highlighting; the editor's existing highlighted preview is unaffected.
- Copy and download the selected readable text file; report clipboard failures.
  Unsupported binary formats and read errors disable these actions and show a
  localized message. Native Office/PDF preview and original binary downloads are
  not added by this change.
- Installed detail reuses the existing permission-controlled file endpoints.
  Repository detail reads its frozen ZIP locally, strips a shared archive root,
  decodes supported UTF-8 text and reports malformed archives. When ZIP data is
  absent, use available SKILL.md content from the frozen metadata snapshot.
- Python UT: not applicable to these frontend-only changes. Reuse existing
  contracts; no new D1 quota or formal case is introduced. Browser/D4 visual
  acceptance and full application type/build verification remain unverified.
- Native file-tree UT: `node --test frontend/tests/component/skillDetailFiles.test.mjs`,
  2 tests passed (nesting, duplicate basenames, filtering and empty results).
- Isolated component UT: `skillReadOnlyDetail.test.tsx` and
  `repositorySkillDetailFiles.test.tsx`, 7 tests passed in Vitest 4.1.12 with mocked
  Markdown rendering. This verifies file interaction and ZIP/error contracts,
  not visual fidelity or live backend permissions.

### Installed skills view

- Reuse the three-column responsive grid, icon mapping, single header tag row,
  two-line description, author and installation count styling for `view=mine`.
  The per-card edit/delete/publish menu remains at the top-right in this view.
- Search, tags and creator ownership remain server-backed. The existing ownership
  contract supports all/self/others, not selecting individual creator identities.
- Move form creation from the empty create-card slot into a persistent toolbar
  dropdown; it remains available when the list is empty or filtered. Workbench
  creation navigates to the existing localized workbench; selecting skill creation
  there remains necessary because this checkout has no supported creation-mode link.
- Batch management is opt-in; only EDIT resources can be selected for deletion.
  Leaving/re-entering batch mode or changing filters resets selection. Existing
  confirmation, partial failure reporting and cache invalidation remain in use.
- Management mode replaces create/layout actions with delete, refresh and exit;
  selected count, clear selection and select-current-page appear above the grid.
  Card selection replaces the per-card action menu in the top-right header.
  Clicking a card does not open its detail while managing; list mode uses its
  existing table selection. Refresh clears selection before refetching, and an
  empty result still renders disabled management controls and the exit action.
- Restore the existing cards/list switch in the installed-skills toolbar in both
  layouts. Cards remain the default; switching uses the existing URL state and
  pagination reset behavior. Do not add a sort control to this view.
- Retain real repository review and publishing controls beyond the minimal reference
  screenshot. Do not fabricate author emails: display the available `created_by`
  field and a missing-value placeholder when necessary.
- Python UT and new formal cases remain inapplicable to the visual adjustments;
  component/journey regression for the toolbar is required but BLOCKED by dependency
  preparation in this environment. Do not treat icon unit tests as toolbar proof.

- Traditional Python UT: exempt; no Python, API or business behavior changes.
- Frontend regression: reuse `frontend/tests/component/skillRepositoryInstallAction.test.tsx`
  for direct installation, installed/unknown copy menus and pending actions.
- Frontend icon mapping UT: `node --test frontend/tests/component/skillRepositoryIcon.test.mjs`
  covers document/presentation success, metadata precedence, missing/unknown metadata
  and token boundaries. This uses Node's native TypeScript support (Node 24 locally).
- Formal D1–D5: no new cases or bindings for this visual-only change; no existing
  cases removed. Visual browser acceptance remains unverified until the frontend
  is rebuilt with these source files. Component tests do not establish visual fidelity.

## Evidence

- Copyright header check: passed for the four changed TSX source files.
- `git diff --check`: passed.
- Icon mapping UT: 3 tests passed. No Python UT or formal Case execution is claimed
  from these frontend unit results.
- Prettier syntax/format check uses the repository `.prettierrc` in an isolated
  container directory; the running application's files are unchanged.
- Full dependency preparation is blocked by the existing peer conflict between
  `@assistant-ui/react-ai-sdk` and `ai`. Project dependency declarations are unchanged.
- The minimal temporary dependency harness also failed during npm preparation
  (`Cannot read properties of null (reading 'edgesOut')`). Component regression
  execution is BLOCKED, not passed. Full type/build and browser checks are also
  unverified; no application deployment is claimed.

### Management regression follow-up

The earlier preparation failures above describe the original full-project setup.
An isolated minimal harness subsequently succeeded using npm 11 with `--include=dev`
and `NODE_ENV=test` (the application container defaults to production mode).
The repository dependency files and running application were not changed.

- Harness: `/tmp/skill-batch-regression` in the web container; Vitest 4.1.12,
  React 19.2.3 and Ant Design 6.3.0. This is a targeted isolated run, not the
  configured full dependency set/build.
- Command: `node node_modules/vitest/vitest.mjs run tests/component/skillBatchSelection.test.tsx tests/component/skillRepositoryInstallAction.test.tsx`.
- Result: 2 files, 8 tests passed. Three new tests cover selection permission,
  select-page/clear, confirmation before mutation, deletion success, and retaining
  selection plus the error message on failure. Five existing install-action tests
  passed independently of the icon mapping UT.
- Copyright, translation JSON/key validation, Prettier parsing/formatting and
  `git diff --check` passed for this adjustment.
- Browser screenshot/portal layout acceptance, full type/build checks and formal
  Case execution remain unverified. These component results do not certify them.
