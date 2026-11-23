---
name: tfp-verification
description: Generate a deterministic report for disposable executor acceptance tests.
---

Use `read_skill_config` to retrieve this Agent's marker and numeric value.
The verification script is `scripts/report.py`. It accepts `--nonce` and
`--value`, writes one UTF-8 report in the execution output directory, and
prints its relative filename. Use `upload_to_s3` to publish that report.
