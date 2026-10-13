# Nexent model profile source catalog

## Source and scope

Selected authored TOML files are copied byte-for-byte from
[models.dev](https://github.com/anomalyco/models.dev), commit
`e69e1844210e5cfe7c7e7f68d57328bc7451a51c`.
The original MIT copyright and permission notice is retained in [LICENSE](LICENSE).

The initial inventory contains 21 model files, 21 provider-model files and three
provider files for Alibaba China, Volcengine and Volcengine Coding Plan. It covers
selected recent Qwen, GLM, DeepSeek and MiniMax models. This is source material,
not a verified support list. Pricing remains reference data; this change does
not implement cost estimation.

## File ownership

- `models/` and `providers/` retain upstream paths, spelling, comments and bytes.
- `manifest.toml` pins source kinds, paths, hashes and the upstream revision.
- Nexent normalization and API binding rules belong under `rules/` separately;
  do not silently rewrite upstream files.
- Source references are provenance. Saved outlets retain their resolved
  configuration and do not recompose it when the catalog changes.

## Updating the selection

1. Select one upstream commit and inspect its authored schema and generator.
2. Copy reviewed files and their complete `base_model` dependencies.
3. Preserve original bytes and paths; update manifest hashes and revision.
4. Review every field against the versioned Nexent mapping rules, including
   fields retained as references or explicitly ignored.
5. Run integrity, parser, normalization, composition and installed-package
   checks. Run the reusable real-model matrix before declaring support.
6. Keep deleted upstream entries locally unless deliberately removed in a Nexent
   release; do not modify saved outlets automatically.

No upstream TypeScript project, online synchronization or npm dependency is
required at runtime. Model weight licenses and service terms remain separate
from the license of these descriptive files.
