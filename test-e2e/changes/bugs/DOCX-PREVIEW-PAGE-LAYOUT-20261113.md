# DOCX preview background and missing page layout — 2026-11-13

## Reproduction and scope

The conversation artifact viewer opened a generated `simple_document.docx`
containing three paragraphs and no `w:sectPr`, page size or page margins. The
pasted XML demonstrates the missing section metadata. The shared viewer used
`bg-gray-200` around a renderer page that collapsed to its text height. This
produced a small white text strip and a large gray panel, as in the user image.

`RawStreamPreviewViewer` owns byte retrieval, format selection, Office rendering
and unsafe-link hardening; chat artifact panes reuse it. The document is not
rewritten or uploaded by this fix. No deployment or environment data is changed.

## Expected behavior and implementation

- The DOCX viewport uses the shared white sliding-panel background token.
  Existing transparent renderer wrapper and shadow removal remain scoped.
- Missing page width/height use an A4 fallback; missing padding uses one-inch
  page margins. The fallback width fits a narrow panel. Explicit inline page
  dimensions, orientation, height and zero/custom margins are preserved.
- Changes are confined to actual `.docx-wrapper > section.docx` pages. Reapplying
  defaults is idempotent; adjacent content is untouched.
- PDF, spreadsheet and presentation rendering are unchanged. Existing unsafe
  link neutralization and disabled HTML altChunk rendering are retained.
- Document-defined page backgrounds are not replaced; only the viewer backdrop
  changes to white.

## Evidence and verification boundaries

Traditional UT decision: strengthen the shared viewer component test and add
targeted DOCX tests; reuse existing sanitizer and file-kind unit tests. There is
no Python/backend behavior change requiring Python UT. Existing UT/formal assets
are preserved. No additional D1 quota or formal execution PASS is claimed.

- `frontend/tests/component/docxPageLayout.test.tsx`: real JSZip OOXML and real
  docx-preview rendering prove missing metadata, landscape/custom margins,
  partially specified layouts, multiple pages, idempotence and sibling isolation.
- `frontend/tests/component/rawStreamPreviewViewer.test.tsx`: proves defaults
  are called after rendering; existing altChunk/link and PPTX group assertions
  remain active.
- `frontend/tests/component/officePreviewSanitizer.test.tsx`: existing 19 tests.
- `frontend/tests/officePreview.test.ts`: existing six native Node tests.

Results: 26 component tests and six native Node tests passed. Component tests ran
in an isolated temporary directory with Vitest 4.1.12, React 19.2.3 and the
repository's docx-preview 0.4.1. This is not the complete frontend dependency set.

Real browser checks used an independent headless Edge profile and temporary HTML
produced by the real DOCX renderer and application defaults/styles. Default and
narrow views had white viewport/page backgrounds and a full paper height;
landscape dimensions and zero top margin were preserved. The default view was
also visually inspected. These fixture checks are separate from formal D4 and
do not establish the deployed application's end-to-end behavior.

The sibling SPEC repository/UI source is unavailable; SPEC integration and formal
ownership mapping remain incomplete. Full application type-check/build and live
conversation verification remain unverified because dependencies are not
installed in the checkout and this is a code-only fix. Formal asset validation
requires the missing local openpyxl dependency; no formal acceptance completion
is claimed. Source copyright, formatting and diff whitespace checks apply.

Copyright and `git diff --check` passed. Targeted TypeScript, module CSS and tests
passed Prettier. The global stylesheet retains pre-existing formatting warnings
in its accordion keyframes and scrollbar selector; formatting a temporary copy
confirmed that neither added token declaration caused those warnings. Those
unrelated sections were intentionally not rewritten.
