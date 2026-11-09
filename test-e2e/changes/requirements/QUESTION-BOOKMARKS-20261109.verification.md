# Question bookmarks verification

Implementation uses an owner-private boolean on user-message rows. GET and PUT
question bookmark endpoints authenticate identity and scope the operation to an
undeleted owned conversation and undeleted user message. PUT sets desired state
instead of flipping it. Message and conversation activity timestamps are preserved.
The additive migration leaves existing messages unmarked. Branch copying omits
the bookmark column, so new branches start without copied bookmarks.

The interactive preview opens directly on each hovered/focused tick, allows a
180 ms pointer transfer into the card, and switches adjacent questions without a
tooltip grace corridor. ArrowRight enters the bookmark control; Escape closes
the preview. Bookmarked ticks and the current-reading dot are independent.

Runtime IDs are mapped only when fetched history count and question text agree;
otherwise mutation stays disabled and the user can retry. Loaded numeric message
IDs use their persisted identity. Query keys include account, tenant and
conversation. In-flight writes retain their original query key. Failed writes
retain the last server state; unknown reads and pending writes disable mutation.

## Executed checks

- PASS: frontend component UT, 23 tests in questionDirectory.test.tsx and
  questionBookmarks.test.tsx. Covers original navigation and adjacent-hover
  regression, pointer transfer, explicit mark/unmark, Escape, disabled/error
  state, retry, loaded state, duplicate clicks, late writes after account/chat
  switch, read-only/unsaved chats and runtime-ID alignment/mismatch.
- PASS: 17 Python UT in test/backend/services/test_question_bookmarks.py.
  Controlled session/auth boundaries with real SQLAlchemy statements and FastAPI
  request validation. Checks owner scope, user-message restriction, false/true
  persistence, readback, activity preservation, invalid identifiers/body values,
  missing/foreign resources, authentication and sanitized storage errors.
- PASS: design and implementation asset validators with
  --require-ut-change QUESTION-BOOKMARKS-20261109; no new formal execution passes
  are claimed. Existing formal Cases are preserved.
- PASS: copyright checks on all 15 affected source/SQL/test files and diff
  whitespace check.
- Scoped TypeScript check: zero diagnostics in the six affected production
  TypeScript files using temporary dependency resolution and a CSS declaration.
  This is not a full project type-check: 153 diagnostics remain in the dependency
  tree because the complete frontend environment is unavailable.

## Verification limits

Tests used temporary dependencies outside Git: Vitest 4.1.12, React 19.3.1,
React Query 5.90.12, TypeScript 5.9.3, Python 3.12, FastAPI 0.162.2 and pure-Python
SQLAlchemy 2.0.45. Windows application control blocked the compiled SQLAlchemy
extension. These checks do not establish the locked Python 3.11/full npm baseline.
Full project build, browser layout/pointer journey, deployed API/database
persistence, cross-browser recovery and migration rollout remain BLOCKED pending
a prepared deployment/test environment. No live application data was mutated.

The sibling nexent-doc and authoritative ../docs/前端ui.md are absent. External
SPEC synchronization, formal Feature/Case authoring and D2/D4/D5 runtime proof
remain pending; this delivery does not claim formal acceptance completeness.
No deployment, commit, push or target-branch merge was performed.

## Deployment

Build both main and web images with the latest tag, then use the existing Docker
deployment script with local-latest. Deployment must apply the new
v2.9.0_009_question_bookmarks.sql migration before the updated backend starts.
Do not merely restart the web container or reuse its old image.
