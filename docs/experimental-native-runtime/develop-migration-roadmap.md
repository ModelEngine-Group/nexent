# Introduction and future integration

The current branch is based directly on develop and targets develop in draft PR4315. Its model-service integration is implemented here rather than deferred to a future migration. The v2.8.4 branch is a standalone hotfix-like experiment and is not intended to merge into either main or develop.

Before enabling the new mode, select and validate model/provider profiles and retain their resolved capability/parameter configuration. Set NEXENT_AGENT_RUNTIME=toolcalling and recreate application services. Models without declared tool support continue through CodeAgent. Rollback is the default codeagent setting; no Agent Definition schema migration is introduced by the runtime.

Future work includes native-history compaction, multimodal projection, provider-specific opaque reasoning continuation and the explicitly unverified harness journeys in the compatibility matrix. Those are separate from the completed generation-terminal and staged-text contract. Reconcile current develop and repeat required verification before merge; no branch protection or workflow settings are changed by this feature.

Host deployment data for PR4315 is separate from the earlier experiment. Preserve both worktrees' private deployment directories while either installation is required. The VM remains stopped by user preference.
