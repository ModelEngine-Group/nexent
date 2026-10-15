# Legacy avatar options

The high-fidelity editor displays the same five ordered icons used by getAgentIcon. DEFAULT_AGENT_ICONS is the shared source of truth; its ordering must preserve the ID modulo mapping.

AgentAvatarOptions is presentational. The parent supplies disabled state, optional selected key and a callback receiving the stable key and rendered SVG. Buttons have localized labels, tooltips and aria-pressed. They wrap to fit narrow layouts and remain visible when disabled.

The parent owns upload state and a synchronous in-progress guard covering conversion and upload. Selection converts a clone of the rendered SVG to a 200px PNG through createAgentIconFile, then uses the existing file-upload endpoint. Canvas/decode/encoding errors report failure without replacing the current draft avatar. Temporary object URLs are always released after allocation. SVG geometry remains sourced from Lucide, not duplicated path data.

Saved images persist through icon_url. No preset key is added to the backend model. The automatic ID choice is highlighted while no image exists; a newly selected option is highlighted during the current editing session, scoped by agent ID and returned image URL. Reloading a saved image preserves the avatar but does not infer a preset identity from its pixels. Uploading a custom image clears the current preset highlight.

Read-only, missing-agent and in-progress states disable the presets. Results from a different current agent are not applied to the draft. Custom file uploads, existing validation and agent-list query invalidation remain active.
