# Agent suggestions

Import AgentSuggestion, TextSuggestion or CardSuggestion
from @/components/agent/agent-suggestion. Public types live in @/types/agentSuggestion.
AgentSuggestion requires variant: text or card. Direct style
components share the same props and need no variant.

Pass suggestions (id, title, prompt, optional description, Lucide icon, disabled),
onSelect(prompt, item), optional disabled and className. Both styles own the
same heading through agentSuggestion.heading; callers do not pass heading text.
Supply localized titles/descriptions and full input prompts.
Text shows only title, with a default dot on the left and an aria-hidden right
arrow; an explicit caller icon replaces the dot. The text list is horizontally
centered at max-width 576px. Each outlined row has a 14px radius, at least 46px
height and 16px horizontal padding. The shared heading is centered.
Resource cards
use a deterministic ID hash to select Wrench, Blocks, Sparkles or Library;
explicit icons take precedence. Changing content or item order never changes
the fallback icon. Cards are centered at max-width 672px, with two columns at
container widths of at least 400px and one column in narrower containers.
Outlined cards have a 14px radius, 16px padding, a separate 36px rounded icon tile,
and a title/description stack beside it. Use theme colors and no separate scrollbar.
Enabled cards gain a stronger border, subtle background tint, shadow and a 2px
lift on hover; disabled cards do not highlight or lift. Keep the keyboard focus
ring and suppress motion when reduced motion is requested. Card border/background
hover utilities use important overrides so Ant Design defaults cannot hide them.

The component has no runtime, network or input ownership. Parent decides input
filling/focus/submission and loading/error presentation. Empty lists render null;
all caller items remain visible; native buttons support keyboard activation and
global/per-item disabled states. Resource cards reuse StandardCard. Page spacing
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
