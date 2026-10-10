# Agent first-creation guide: frozen design analysis

Inspected on 2026-10-09 through WeMeeting left-click remote control on the existing Huawei Design **智能体创建** page. No page navigation. Measurements below are source pixels from the right inspector, including the background and mask subtraction children, rather than scaled screenshot estimates. Existing dirty product changes are preserved.

## Measured presentation

Reference artboards are 1920 × 1080. The existing layout has navigation64, assistant561, editor1295, tabs64 and identity74. The four overlays reuse that layout and do not change its fields.

| Element | Inspector contract |
| --- | --- |
| First popover | 300 ×174 including left arrow; white body292 ×174 at local x8; body radius6; source x643/y453; padding L24/T16/R16/B16 |
| Other popovers | 300 ×182 including vertical arrow8; body300 ×174; source step2 x625/y665, step3 x625/y455, step4 x1598/y146 |
| Vertical-arrow padding | Step2/4 L16/T24/R16/B16; step3 L16/T16/R16/B24 |
| Content | Title-to-description gap8; content-to-footer16; first content width260, title24 high and description66 high |
| Title | HarmonyOS Sans SC, Medium500,16px/24px, tracking0, #191919, left aligned |
| Description | HarmonyOS Sans SC, Regular400,14px/22px, tracking0, #777777, left aligned |
| Buttons | Height28, min-width72/max160, padding L/R12 T/B4, radius4; text Regular400,12px/20px; row gap8, aligned right |
| Button colors | Primary #0067D1 / #FFFFFF; secondary white / #191919, border uses source shared #C9C9C9 contract |
| Shadow | x0/y8/blur24/spread0/#000000 at16% |
| Mask | #C4C4C4, multiply blend; full1920 ×1080; equivalent neutral black alpha59/255 when implemented through AntD mask |
| Highlight holes | All radius8. Step1 x63/y10/w563/h1062; step2 x625/y130/w1295/h524; step3 x625/y647/w1295/h359; step4 x1029/y63/w891/h73 |

## Copy and targeting

1. **1/4. 智能对话配置** — 智能体创建与优化助手支持创建全流程指引，可将生成方案一键填充到配置项。可通过快捷卡片尝试开始。 Highlight the whole assistant column; tooltip at its right, arrow near the top. Buttons 全部跳过 / 下一个.
2. **2/4. 智能体核心信息** — 填写智能体描述与头像，选定模型配置并编写提示词，让智能体具备清晰的身份与回复能力。 Highlight basic information plus model/prompt; tooltip below, arrow upper-left. Buttons 上一个 / 下一个.
3. **3/4. 其他自定义配置** — 关联知识库，设置首页欢迎信息，并接入工具、技能与子智能体，拓展智能体的能力边界与使用体验。 Highlight resource configuration; tooltip above, arrow lower-right. Buttons 上一个 / 下一个.
4. **4/4. 调试并发布** — 在调试区验证回复效果与工具调用，确认无误后发布智能体，使其正式对外提供服务。通过发布区提供的接口等信息从外部接入。 Highlight workflow modes and publish action; tooltip below at the right, arrow upper-right. Buttons 上一个 / 开始创建.

## Behavior frozen before implementation

New creation success marks the editor route `?onboarding=1`; normal edit/import/publish routes keep their existing behavior. After authenticated identity, the requested draft and all target elements are ready, show the four-step tour only if this user/tenant has no completion record. Read-only or stale/loading drafts never start it. Previous/next move through the measured targets and scroll the editor internally; tour controls never save, run a model, debug or publish. Start creation dismisses the explanatory overlay and returns focus to the assistant composer; it does not create a second Agent. Skip/Escape/finish persist a versioned completion flag scoped to tenant and user. No server preference endpoint exists, so browser storage implements this frontend-only preference, with in-memory fallback if storage is blocked. No backend changes or fake model answers.

Use AntD Tour/Button and a reusable measured tour shell. Target geometry follows actual modules and viewport resizing rather than fixed artboard coordinates; preserve source tooltip dimensions, type, shadow, arrow directions and highlight radius. Small/short viewports use AntD placement plus a16px viewport constraint and internal scrolling. No new replay entry is added because none appears in the source. No font asset was supplied: CSS names HarmonyOS Sans SC first with existing system fallback; exact proprietary glyph parity remains unverified.

Implementation refinement: while the tour is active, auxiliary name/author/tag fields remain mounted but hidden, model card minimum height is272, and resources are collapsed to match the measured reference. Resource highlight uses a4.5px upward semantic anchor and6.5px vertical gap to reproduce the source's asymmetric hole; dismissal restores the original fields and expansion choices without changing the draft. Creation from both the development list and My Agent repository carries the onboarding marker. Tour popup offsets compensate AntD defaults; the reusable shell constrains the painted panel and arrow together after placement/resize/scroll.

## Code boundaries

`frontend/app/[locale]/agents/page.tsx:handleCreate` and `agent-space/my-agent.tsx:handleAgentCreated` own entry; `[agentId]/page.tsx:AgentSetupContent` owns loaded/permission context; `agent-config.tsx` owns basic/model/resource anchors; `components/agent-config-header.tsx` owns mode/publish anchors. New preference logic is frontend-only. Backend, SDK, model protocol and Agent data contracts are unchanged.
