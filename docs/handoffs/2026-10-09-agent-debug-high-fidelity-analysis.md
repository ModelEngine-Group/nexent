# Agent debug high-fidelity analysis

Source: shared WeMeeting remote-controlled Huawei Design, current intelligent-Agent creation/debug artboard, inspected 2026-10-09 with left clicks only. No navigation to another shared page. Values below come from the right inspector, not scaled screenshot pixels.

| Element / source layer | Frozen values |
| --- | --- |
| Main editor | Navigation64, generation561, remaining configuration1295 at1920; tabs64 and identity74 |
| Content91336860 | Width1261, left16/right18, gap10; configuration763 plus debug488 |
| Debug91336862 /71383 | Width488, height930, white, radius8, padding24; top aligned with configuration cards |
| Header | Inner440×28; title20/28 weight500 HarmonyOS Sans SC #191919; operations24×24, gap16, #4D4D4D |
| Content226434 | Width440, fixed855, top51,left24, space-between; use available height on smaller viewports |
| Welcome71539 | Width440, height360, padding-top192, gap24 |
| Welcome inner | Height168, bottom padding24, gap24 |
| Title91336722 | Centered row356×72, horizontal padding8, avatar72, gap16; text36/54 weight700, #191919 |
| Description91336723 | Width440, height48, horizontal padding8; text16/24 weight500 centered, #191919 |
| Bottom226515 | Width440, height434, top421, gap16 |
| Suggestions | Header50 with top16/bottom12/LR16; text16/22 weight500 HarmonyHeiTi #000; list154, gap8, each46 with radius16/LR12; inner vertical padding12, icon/text gap4; text14/22 weight400 HarmonyOS Sans SC #191919 |
| Composer13411/91336688 | Width440, height164, radius20, padding16, gap8, white; outside stroke0.5 #191919/8%; shadow0 1 6 0 #000/16%; input88 high, controls40 high, gap4 |
| Placeholder |16/24 weight400 HarmonyOS Sans SC, #191919/40%; use existing functional placeholder until skill mentions are supported |
| Footer | Composer/disclaimer gap16, bottom padding16; disclaimer12/18 weight400 HarmonyHeiTi, centered #191919/30% |

Master suggestion component reports890px width while its visible instance occupies440px. Preserve the instance width and responsive filling; do not apply the master width. Hidden master form and off-artboard plate values are excluded.

The background shows soft blue/cyan/purple radial colors. Inspected gradient palette: #669FFF, #66EBFF, #7A66FF fading to transparent. The inspector has not exposed gradient centers/opacity for the right instance, so exact gradient parity remains unverified. No HarmonyOS Sans SC/HarmonyHeiTi font assets exist in frontend/public; declare the source font families and retain fallback. Exact glyph parity cannot be claimed without the assets.

Implementation: keep the configuration tab and identity row spanning both panes; add the debug pane beside the internal card scroll region. Hide the card region during maximize without remounting the debug runtime. The debug header owns clear/fullscreen, with existing compare/planning/close controls reachable through an Ant Design dropdown. Preserve independent single/compare runtimes and existing Agent run/stop interfaces. An opt-in chat presentation supplies welcome and footer slots and composer geometry; default chat and generation presentation are unaffected. Dynamic draft name/icon/greeting/questions must replace design sample content. Suggested question fills the composer without auto-sending. No backend edits or new endpoint; deterministic HTTP mocks are for verification only.

Verification: D1 component callback/data-boundary checks; D4 desktop geometry, question-to-composer, mocked send/stop, clear, fullscreen/restore, compare, constrained viewport and default-chat compatibility. D2/D3/D5 excluded because no protocol/provider/deployment behavior changes.

Delivery: measured layout and runtime controls implemented; fullscreen exit restores previous generation/version panes. Required D1/D4, type-check and production build pass. See [component contract](../frontend/agent-debug-presentation.md) and [verification record](../../test/artifacts/agent-debug-layout-verification.md) for commands, screenshots and global validation limitations. Exact font, gradient geometry and avatar bitmap parity remain unverified.
