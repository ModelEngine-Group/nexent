# Adjacent question preview regression

Observed 2026-11-05 on base `51c227cbe` plus the existing question-rail working-tree changes. The supplied screenshot reports Q3 still displayed while hovering Q2.

## Capability and scope

The question rail maps one native button per current-conversation question to a jump callback. The reading position controls the dark tick and dot independently from the hovered/focused preview. A non-interactive tooltip shows the hovered question and its answer excerpt. Full-directory search remains available. The fix changes only rail TooltipProvider behavior; collection, answer text, jumping and current-position tracking are retained.

## Root cause and correction

Radix Tooltip's default hoverable-content behavior creates a pointer grace polygon between the trigger and the preview. A tall preview creates a polygon overlapping adjacent ticks. While the pointer is inside that corridor, provider pointer-in-transit state prevents the next trigger from opening. The existing `pointer-events-none` CSS on preview content does not disable this internal geometry handling.

Set `disableHoverableContent` on the rail's TooltipProvider. Leaving a tick closes its display-only preview and lets the next tick open, without the hover corridor. Initial hover delay remains 150ms; keyboard focus and the independent reading-position marker remain unchanged. Do not change the shared Tooltip component or other tooltips.

## Acceptance and test responsibility

| AC | Expected behavior | Traditional UT | Formal D1-D5 |
| --- | --- | --- | --- |
| AC-001 | Move Q3 to Q2 inside the former grace corridor: exactly one Q2 preview replaces Q3 | Added adjacent-pointer test in questionDirectory.test.tsx, real Radix with controlled bounding rectangles | No existing bound Case; no duplicate D1 added |
| AC-002 | Leaving Q2 dismisses its preview | Same regression test | No live-browser acceptance claimed |
| AC-003 | Focus preview, jumps, search and active rail scrolling remain valid | Reuse the other 23 directory component tests | Existing formal assets retained |

## Evidence

- Before fix: the focused regression failed with expected `question u2`, received `Q3question u3chat.questions.noReply`. The test positions Q2/Q3 at adjacent 15px rows and uses a tall tooltip rectangle to reproduce the grace polygon.
- After fix: all 24 tests in `frontend/tests/component/questionDirectory.test.tsx` passed with Vitest 4.1.12/jsdom 30.1.3. Temporary dependency resolver/configuration matched the preceding rail verification; no project dependency files changed. Configuration removed after tests.
- Copyright, formatting and whitespace checks passed. Design/implementation strict asset validation is run for both the rail requirement and this bug record.
- Python UT is unrelated. Full locked frontend type-check/build and real-browser visual validation remain unavailable in this checkout without installed project dependencies. Temporary dependency versions differ from the project lockfile.
- The sibling nexent-doc repository is absent. This repository record captures the regression evidence; external SPEC synchronization remains pending. No external SPEC or runtime evidence is fabricated.
