# Selected resource row

Use `SelectedResourceRow` and `SelectedResourceTag` from `@/components/common/SelectedResourceRow` for compact selected resources in Agent configuration. The component is presentation only: callers own catalog data, configuration, removal, permissions, and persistence. Knowledge-base management retains its existing implementation.

`SelectedResourceRow` takes `icon`, `name`, optional `metadata`, optional `actions`, and ordinary div attributes. Optional `nameTooltip` preserves additional real metadata, such as the saved child-Agent version, without adding another visible badge. The name is truncated; its full value remains available in an Ant Design tooltip. Callers supply accessible localized labels on action buttons. The row has no default copy or mutation callbacks.

The shell reuses the previously measured knowledge-base row: `h-12 min-w-0 rounded-[4px] border border-solid border-[#dfdfdf] bg-white px-3 py-2 shadow-[0_2px_8px_rgba(0,0,0,0.08)]`. Name typography is `text-sm font-normal leading-[22px] tracking-[0px] text-[#191919]`. Icon/name and name/metadata gaps are 8px. Metadata remains next to the name; actions use the remaining space at the right edge. Callers use 24px Ant Design text buttons with 14px glyphs and `#777777` color.

`SelectedResourceTag` takes children and optional tooltip text. It uses `rounded-[4px] bg-[#f3f3f3] px-2 text-xs font-normal leading-[18px] tracking-[0px] text-[#777777]`. Long metadata truncates inside the available row width and retains its tooltip. Neither the component nor its consumer may fabricate tags from the visual sample.

Grid ownership remains with the consumer: `grid grid-cols-1 gap-2 sm:grid-cols-2`, selected resources first, then `ResourceAddButton`. There is no nested resource scroll area. The frozen source/measurement distinction and compatibility behavior are documented in `docs/handoffs/2026-10-10-selected-tools-child-agents.md`.

Consumers show at most two real labels/tags plus an overflow count with a title containing the remaining values. Put availability warnings in the fixed action region, outside clipped metadata, to keep them visible alongside the configuration and removal controls.
