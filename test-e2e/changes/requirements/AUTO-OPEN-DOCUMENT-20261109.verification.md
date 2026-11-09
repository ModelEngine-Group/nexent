# Automatic document display

The thread observes live artifact publication, waits for the run to finish and
opens a new supported document beside chat. Restored history is the baseline,
not a new output event. Scope changes and loading clear preview selection;
manual close suppresses reopening for the same run. Artifact storage identity
deduplicates token/metadata updates. Files without a real source stay pending.
Office originals take precedence over companion PDFs; scripts are not automatic
preview candidates. The artifacts list still permits explicit preview selection.

The document panel owns its localized title/list/download/close controls. On
large screens it is a sibling column; on narrow screens it fills the viewport.
The shared file viewer has an additive content-only inline presentation, while
its drawer and fullscreen defaults remain unchanged. Original docx/xlsx/pptx
bytes use the existing sanitized stream renderer. Legacy Office formats retain
the existing converted preview endpoint. No backend, model or file-generation
behavior changes, editing, native application launch or database changes apply.

## Verification

- PASS: 31 component tests across autoArtifactPreview.test.tsx,
  artifactDocumentPanel.test.tsx, inlineFilePreview.test.tsx and the existing
  rawStreamPreviewViewer.test.tsx. Covers completion timing, late uploads,
  history/scope/loading isolation, close/manual reopen, primary-document choice,
  unsupported/process files, source URLs, panel actions, inline/drawer/fullscreen
  compatibility, embedded Office HTML sanitization and PPT group rendering.
- PASS: 6 existing standalone Node tests in frontend/tests/officePreview.test.ts.
- PASS: design and implementation asset validators with
  --require-ut-change AUTO-OPEN-DOCUMENT-20261109. Existing formal Cases are
  preserved; static asset validation is not browser/runtime acceptance.
- PASS: copyright checks on all nine affected source/test files and diff
  whitespace checks. New component/hook/test files use project Prettier settings.
- LIMITED: scoped TypeScript check reports only missing next/dynamic in the six
  selected affected production files. The full dependency tree has 136
  diagnostics in this temporary environment. Full project type-check/build is
  BLOCKED by missing complete frontend dependencies, not reported as passing.

Tests use temporary dependencies outside Git, including Vitest 4.1.12 and React
19.3.1. PDF loading is a controlled deferred-component boundary in component
tests; actual browser PDF rendering is not claimed. Existing OOXML parser tests
control fetched content and parser output; they are not a real generated-document
end-to-end check. Python UT is unrelated to this frontend-only change.

Actual deployed document generation, visual layout, narrow-screen behavior and
authenticated file preview/download require browser integration verification.
The external nexent-doc and ../docs/前端ui.md sources are unavailable; SPEC
synchronization and formal D4 journey acceptance remain pending. No deployment,
production data mutation, commit, push or target-branch merge was performed.
Other pending bookmark, annotation and rail changes were preserved.
