# Measured explanatory tour

Source: same-page inspector analysis in `docs/handoffs/2026-10-09-agent-first-creation-guide-analysis.md`. Shared implementation: `frontend/components/common/StandardTour.tsx`, based on AntD Tour/Button. Use this shell only for the measured onboarding contract, not unrelated popovers.

- White body, `p-4 rounded-[6px] min-h-[174px] shadow-[0_8px_24px_0_rgba(0,0,0,0.16)]`; body width300, or292 for left arrow extending8, constrained to viewport minus32.
- Title `text-base font-medium leading-6 tracking-normal text-[#191919]`; description `text-sm font-normal leading-[22px] text-[#777777]`; gap8, footer margin16.
- Buttons `h-7 min-w-[72px] max-w-[160px] rounded-[4px] px-3 text-xs leading-5`, row gap8, right aligned. Primary #0067D1; secondary border#C9C9C9. No dots or close icon in the source.
- Mask uses the equivalent neutral black59/255 alpha for source #C4C4C4 multiply blend. Callers supply real targets, highlight radius8, collision-safe placements, localized copy and previous/next/dismiss actions.
- Tour blocks interaction with highlighted business controls. Callers must handle Escape, initial/final focus and scoped browser preference without saving configuration or invoking business actions. Browser-local preference is not server synchronization.
- Use HarmonyOS Sans SC with system fallback; no proprietary font file is bundled by this contract.
- The shell observes AntD popup placement and keeps the painted panel/arrow at least16px inside the viewport. Workflow-specific source offsets are CSS variables on the caller class; no absolute artboard placement is used in product code.
