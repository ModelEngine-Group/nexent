# Ubuntu Daily shared results

Ubuntu opts in with `daily-launch.py --publish-latest`. This is an explicit launcher option, not a new environment variable or pipeline setting. Other developer and Windows entrypoints remain unchanged. The destination is `<test-home>/runs-ubuntu`, derived from the selected test home.

Publication happens after a complete D0-D6 batch and before the existing notification. Complete batches with failed tests are published; incomplete batches are not. Publication failure does not change test outcomes and must not suppress the existing complete-run notification. No publication code sends or retries messages.

Only `latest-report.md` and `latest-batch.zip` are managed. Batch IDs, pinned HEAD, Beijing timestamps and original evidence paths remain in the report. Shared reports explain that `cases/`, `logs/` and `checkpoints/` paths are relative to the extraction directory. The files are Syncthing copies, not Feishu attachments; compare batch IDs because the two files can arrive independently. The package's own report and logs form one consistent snapshot.

The package includes all selected Cases' text logs, receipts, summary, checkpoints and ownership metadata. It excludes config/env files, resolved asset configurations, inputs, dependencies, raw materials and successful screenshots. Existing config credentials and common wire credentials are redacted from text. Unreviewed binary screenshots and raw Playwright traces cannot be certified safe through text replacement: they remain on Ubuntu and are listed in `excluded-evidence.json`. This publication mechanism does not provide reviewed-binary release yet. The report explicitly states that limitation; original evidence is not removed.

`manifest.json` identifies the batch and hashes every payload file. Build/verify under the ignored `state/` tree, then replace the fixed destination files with rollback on local replacement errors. Refuse symlinks and unexpected existing destination entries rather than removing historical data. Publication receipts are stored under `state/report-publications/<batch>/receipt.json`. Original batch receipts, summary and checkpoint results are never rewritten by the publisher. The normal runner only refreshes its reading report with publication status before notification.

For an already complete historical batch, use the dedicated test-home Python:

```bash
"$TEST_PYTHON" "$REPO_ROOT/test-e2e/infra/tools/suite_publish.py" \
  --test-home "$TEST_ROOT" --batch "<absolute-existing-Daily-batch>"
```

This standalone command does not synchronize Git, deploy, prepare assets, run tests or send messages. Optional `--ownership-file` accepts an attribution-only historical overlay whose HEAD and Case identities must match the original batch. It cannot override test outcomes.

Ubuntu's existing Syncthing ignores `runs/`, `reports/`, `runtime/` and `state/`; keep those exclusions and allow `runs-ubuntu/`. Do not change the entire test-home share to send-only if it is still used for bidirectional asset collaboration. Receiving devices should not edit published files and should disable or bound their version retention to prevent old archives accumulating. No code here changes Syncthing configuration or deletes original history.

For a report-only receiving device, use receive-only mode and a device-local `.stignore` allowlist. Pause the folder before changing its root or ignore rules, preserve its existing configuration, and resume only after the rules are in place. This excludes local configuration, credentials, historical results and extracted packages without deleting them:

```text
!/runs-ubuntu/latest-report.md
!/runs-ubuntu/latest-batch.zip
/runs-ubuntu/**
!/runs-ubuntu
*
```

Apply this only on report receivers, not on an Ubuntu sender still sharing test assets. These rules do not alter other devices' ignore settings.

When enabling the workflow option for the first time, update the idle Ubuntu checkout to the merged `develop` revision before triggering Actions. The workflow invokes the local launcher before that launcher fetches code; an old launcher does not yet recognize `--publish-latest`. Do not switch or pull the checkout while a batch is running.
