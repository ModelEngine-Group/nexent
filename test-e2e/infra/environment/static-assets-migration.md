# Static assets migration

## Current inventory and boundary

The original suite contains 23 inventory-listed payloads, about 2.16 MB in total
(26 files including manifest, example and an Excel lock file). Four audio files
total 1,133,249 bytes. Their names alone do not establish safe content or licence.
The 23 catalogued payloads have now been copied into the repository working
tree under `infra/assets/`, without changing their bytes. They have not been
committed or pushed. No local configuration or secrets file was copied. The existing inventory remains under
`infra/migration/source-audits/v5-asset-inventory.yaml`. The exact relative
paths, sizes and hashes from the original asset manifest are in
`infra/assets/catalog.json`; no test uses a source machine's absolute path.

Static files are inputs, not asset factories. `anchors: true` provisions/checks
configured identities/models; it does not download or generate the audio files.
`d3.assets.asset_path()` currently resolves configured relative paths against
`NEXENT_TEST_HOME` and fails when the requested file is missing.

## Provisioning and execution checks

`infra/tools/static_assets.py` uses the catalog and copies only missing files.
It refuses differing destinations, source drift, symlinks and path traversal.
It writes a local receipt under `<test-home>/state/`. For example:

```sh
python test-e2e/infra/tools/static_assets.py plan --test-home /test-data --source-assets test-e2e/infra/assets
python test-e2e/infra/tools/static_assets.py apply --test-home /test-data --source-assets test-e2e/infra/assets
python test-e2e/infra/tools/static_assets.py verify --test-home /test-data
```

The new suite checks the whole catalog at D0 for Daily. A targeted run checks
catalog entries referenced in the selected Case contract, its primary script
or `required_assets`; a declared directory selects that catalog category.
Missing or changed selected entries stop the batch with a local D0 receipt.
The Windows source, repository copies and isolated output test home were checked
against all 23 entries. This verifies content transfer, not media licensing or
product behavior.

## Remaining rollout

1. Provision the machine-local `NEXENT_TEST_HOME/assets/` from the repository
   `test-e2e/infra/assets/` for initial parity. The 23 catalogued payloads are
   present in the repository working tree; `~$` Office locks, old manifests,
   reports, credentials and runtime directories were excluded. Do not change
   users/models/secrets configuration during provisioning.
2. Reconcile the 23 catalog files with actual helper and Case references.
   Some legacy Case prose mentions `vlm_expected.json` or `kb_expected.json`,
   which is absent from the original asset manifest and source directory.
   Determine whether those are stale prerequisites or missing fixtures; do not
   synthesize expected media content or silently count them as present.
3. Before committing or publishing the copied payloads, review content,
   licence and privacy. Move any unsuitable payload back to machine-local
   storage and adjust the catalog/Case dependencies explicitly. Do not replace
   an existing audio sample with silence, or another image/video, without
   updating and verifying its semantic oracle.
4. Extend catalog metadata and preflight with explicit PCM sample format/rate,
   transcript pairing and media distribution decisions. Current checks validate
   exact bytes, WAV framing, even raw PCM sample length and STT oracle JSON.
   They do not infer sample rate or transcript correctness from a `.pcm` name.
5. Verify the same samples against the original suite on the same product commit
   before enabling repository Daily. Keep original files recoverable.

## Repository copies and pre-commit review

| Assets | Current placement | Before commit/push |
| --- | --- | --- |
| STT PCM/WAV, MP3 and expected transcript | `infra/assets/audio`, `infra/assets/expected` | verify speech content, origin and oracle |
| Images and video | `infra/assets/images`, `infra/assets/video`, `infra/assets/d4` | review rights/privacy and expected visual content |
| Word/PDF/Excel knowledge/evaluation samples | `infra/assets/documents`, `infra/assets/evaluation`, `infra/assets/d4` | inspect embedded metadata, links and personal information |
| Synthetic sentinel text and malformed fixtures | `infra/assets/knowledge`, `infra/assets/d4` | verify content/oracle |
| Agent/Skill import examples | `infra/assets/agents`, `infra/assets/skills` | check embedded environment IDs/credentials without silently changing test intent |
| Asset checklist | `infra/assets/` | confirm whether this workbook is needed at runtime |
| Old manifest, manifest example and Office lock | excluded | not runtime fixtures |

Catalog/provisioning and D0 checksum checks are implemented. Repository copies
are uncommitted. Reference reconciliation, distribution review and stronger
media semantics above are pending.
