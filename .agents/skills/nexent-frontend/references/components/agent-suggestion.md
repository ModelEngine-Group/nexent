# Agent suggestions

Import AgentSuggestion, TextSuggestion or CardSuggestion
from @/components/agent/agent-suggestion. Public types live in @/types/agentSuggestion.
AgentSuggestion requires variant: text or card. Direct style
components share the same props and need no variant.

Pass suggestions (id, title, prompt, optional description, Lucide icon, disabled),
onSelect(prompt, item), optional disabled and className. Both styles own the
same heading internally through agentSuggestion.heading (你可以这样问我).
Callers do not pass heading text.
Supply localized titles/descriptions and full input prompts.
Text shows only title, with a default dot on the left and an aria-hidden right
arrow; an explicit caller icon replaces the dot. The text list is horizontally
centered at max-width 576px. Each outlined row has a 14px radius, at least 46px
height and 16px horizontal padding. The shared heading is centered.
Resource cards
use a deterministic ID hash to select Wrench, Blocks, Sparkles or Library;
explicit icons take precedence. Changing content or item order never changes
the fallback icon. Cards use the workbench single-column list style, with 8px
row spacing, 12px button radius/padding, 16px muted icons, a 14px medium title
and a 12px description (20px line height). The shared localized heading
is left aligned. No outlined card container, colored icon tile, grid, lift or shadow.
Enabled rows gain a subtle accent hover background. Disabled rows do not highlight;
retain native keyboard activation/focus rings and reduced-motion support.
The card list defaults to max-width 672px; workbench can use max-w-none.

The component has no runtime, network or input ownership. Parent decides input
filling/focus/submission and loading/error presentation. Empty lists render null;
all caller items remain visible; native buttons support keyboard activation and
global/per-item disabled states. Card rows use native button content. Page spacing
belongs to the parent; avoid adding page-specific layout flags here.

Newchat Thread and the NL2Agent panel directly compose these
components inside the shared AgentWelcome: greeting above, suggestions in the
middle, with Thread owning the bottom composer. Neither welcome owns an input
or recommendation scroll container. NL2Agent's panel owns its localized resource
items; all welcome interaction adapters disable selection while running/read-only.
AgentWelcome separates the greeting and suggestion sections by a uniform 96px
(gap-24), with no responsive spacing override.
NL2AGENT_DEFAULT_SUGGESTIONS in const/nl2agent.ts defines stable IDs and title,
description and prompt translation keys for four default questions. The panel
resolves the keys, injects full prompts into example_questions and composes
AgentWelcome/CardSuggestion directly. Explicitly setting showOptimizationSuggestions
to false hides the cards. Running state is subscribed from the local runtime.

Workbench CreationExamples now composes CardSuggestion for both Agent and Skill
creation, preserving its runtime/composer focus and visibility rules. It shares
Agent creation definitions with NL2Agent; description-based mode selection remains
owned by the panel. This 2026-10-20 style supersedes the prior card grid design.

Agent debug also composes AgentWelcome and TextSuggestion: title/avatar/greeting
and all legacy questions share the thread viewport, while composer/disclaimer stay
at the bottom. Debug disables question selection while running. AgentWelcome accepts
className for natural-height embedding; debug uses it instead of height-dependent
top padding or a question-only footer scrollbar.
