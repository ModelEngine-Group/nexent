# Shared UI maintenance

`components/ui` is the fixed upstream layer. All 24 source files, including the responsive hook, come from commit `4aaea19d9cff3e0908e12a8c1d504b8c5ec34610`. Only import paths, copyright headers and deterministic formatting are adapted. Raw and generated snapshots retain the exact source and applied transform; `check:ui` rejects changes to the adopted files. The upstream MIT license is retained.

`components/common` owns shared project contracts. `Button` is the single project button, with dimensions, brand-color interaction states, safe native defaults and optional pending/icon behavior. Submission uses `type="submit"`; there is no separate SubmitButton implementation. All StandardButton callers have migrated to Button; the compatibility entry is deleted. Native button/link behavior stays in Button, including disabled/loading link guards. Badge owns project status variants and sizes. Dialog/Sheet content owns project layers and retained mounting; Popover/Tooltip own shared overlay layering. Modal adds its content and close/action contract; the one-consumer preview drawer shell belongs to preview. Avoid wrappers that only rename or forward unchanged props.

`components/common` also contains cross-domain composed interactions: CopyButton owns clipboard feedback, and ExpandEditModal owns long-text draft/confirm/cancel interaction shared by agent editing and resource management. They compose common controls without requests or domain state.

Domain components live in their own directories: agent workflows in `components/agent`, conversation controls in `components/chat`, resource controls in `components/resources`, and file preview/CSV/PDF components in `components/preview`. Callers retain requests, permissions and domain state. The global semantic theme supplies brand-color without copying palette values into wrappers.

## Ownership and provenance

Every basic source has a verified immutable source path, raw/generated snapshot and SHA-256 in `manifest.json`. Project-specific loading UI has moved out of ui. Existing historical sources have been replaced by the pinned upstream originals; compatibility belongs outside ui. The `radix-new-york-v4-v2` transform adjusts imports/header/formatting only, including keeping the pinned responsive hook next to the basic controls.

The selected compatible registry is `new-york` (the pinned upstream new-york-v4 sources use Radix). Tailwind 4 uses CSS configuration and an empty `tailwind.config` field. The old unused JS configuration has been removed. The recorded CLI is 4.23.0; a CLI version alone does not pin registry contents. Do not run init or overwrite-all in the application tree.

## Routine changes

1. Change colors through semantic tokens. Keep business logic outside ui.
2. Do not edit basic-control source for project needs. Change common/domain components instead. A wrapper needs shared behavior or a stable project contract, not merely shorter JSX. Adopt upstream fixes through an explicit source update.
3. Run `npm run check:ui`. The legacy import budget is frozen by file, package and imported member. Remove exceptions as consumers migrate; do not regenerate it to approve new Ant Design usage. Moving a legacy file requires an explicit reviewed exception move.
4. Run relevant component UT, `npm run test:ui-tools`, type-check and affected visual/keyboard checks.

## Upstream updates

The frontend maintainer checks monthly, prioritizing security/accessibility/functional fixes. Use separate dependency and source-update PRs. Preserve source URLs, commit, hashes, generation configuration and local-change rationale in the manifest.

Inspect provenance and local modifications:

```powershell
npm run ui:upstream -- status
```

Preview one component at an immutable 40-character commit. Use an absolute, new candidate directory under the workspace's dated artifacts/misc area, outside frontend:

```powershell
npm run ui:upstream -- preview button --ref <40-character-commit> --output <absolute-candidate-directory>
```

The preview downloads only the recorded upstream source path, applies the fixed transform and runs `git merge-file` against the last generated baseline and current local file. It writes raw/generated/base/local snapshots, merged.tsx and candidate.json in that isolated directory. It never updates application code. Unknown ancestors, baseline corruption, mutable refs and unsupported bases are rejected. A source that starts requiring new registry dependencies must have its generation/dependency contract reviewed before adoption.

Review the upstream difference and the merged result, dependencies, local fixes, accessibility and theme impact. Resolve any conflict markers in merged.tsx. Accept the reviewed candidate:

```powershell
npm run ui:upstream -- accept <absolute-candidate-directory> --reviewed
# Only after manually resolving a conflicted preview:
npm run ui:upstream -- accept <absolute-candidate-directory> --reviewed --resolved
```

Acceptance rejects stale working files/configuration, changed upstream candidate data and unresolved conflicts. It updates the target, adopted baselines and metadata together, restoring prior contents on a write failure. These commands require exclusive access to the affected working files; they are not a concurrent transaction service. Do not commit until component/tool UT, type-check, relevant browser/visual checks pass. If validation fails, restore the complete target/baseline/manifest change together. Acceptance records adoption, not proof that product tests passed.

Keep the candidate/evidence paths in the PR or task record. New registry styles, generator transforms, public API changes and dependency changes require explicit review. The tool deliberately does not auto-install newly discovered dependencies or auto-publish changes.

## Current migration boundary

The common directory now has zero Ant Design and @ant-design/icons imports. Shared buttons, input adornments/clearing, modal shells, loading indicators and domain-owned preview/citation/guide controls use native or Radix/shadcn components. Standard compatibility entries have been removed; the unused StandardTable wrapper was removed. Informational notices survive preview unmounting through NoticeHost.

Business pages and domain components, nested providers, most notifications and remaining icon imports are subsequent migration work. The root Ant Design bridge remains while those consumers exist. A passing import-budget check does not certify full application removal. The checker rejects Ant Design in common even if an old budget entry is present.
