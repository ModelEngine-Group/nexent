# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Exercise the selected user's actual Node resolution and browser installations."""
import os
from pathlib import Path
import shutil
import subprocess


JSDOM_PROBE = """
const {createRequire} = require('node:module');
const load = createRequire(process.argv[1]);
const {JSDOM} = load('jsdom');
const dom = new JSDOM('<p style="color:red">runtime probe</p>');
if (dom.window.getComputedStyle(dom.window.document.querySelector('p')).color !== 'rgb(255, 0, 0)') {
  throw new Error('jsdom CSS dependency closure is not usable');
}
dom.window.close();
"""
BROWSER_PROBE = """
const {createRequire} = require('node:module');
const load = createRequire(process.argv[1]);
(async () => {
  const options = {headless:true};
  if (process.argv[2]) options.channel = process.argv[2];
  const browser = await load('playwright').chromium.launch(options);
  try { const page = await browser.newPage(); await page.setContent('<p>runtime probe</p>'); }
  finally { await browser.close(); }
})().catch(() => { process.exitCode = 1; });
"""


def node_toolchain_problems(repo: Path, home: Path, frameworks: set[str]) -> list[str]:
    """Probe in child processes, without installing or changing shared dependencies."""
    node = shutil.which("node")
    if not node:
        return []  # The caller reports the missing Node executable.
    probes = []
    if "vitest" in frameworks:
        probes.append(("D1 jsdom/CSS dependency resolution (including nested permissions)",
                       "test-e2e/infra/automation/d1/frontend", JSDOM_PROBE, ""))
    # Custom D1 browser checks import through the product frontend, independently of D4.
    if "custom" in frameworks:
        probes.append(("product frontend Chromium/headless-shell", "frontend", BROWSER_PROBE, ""))
    if "playwright" in frameworks:
        # D4's fixed config uses the full Chromium channel for attachment downloads.
        probes.append(("D4 full Chromium", "test-e2e/infra/automation/d4", BROWSER_PROBE, "chromium"))
    env = dict(os.environ, PLAYWRIGHT_BROWSERS_PATH=str(home / "runtime/playwright-browsers"))
    problems = []
    for label, relative, script, channel in probes:
        try:
            result = subprocess.run([node, "-e", script, str(repo / relative / "package.json"), channel],
                                    cwd=repo, env=env, capture_output=True, text=True, timeout=30)
            if result.returncode:
                problems.append(f"unusable locked {label}; run bootstrap as the test user")
        except (OSError, subprocess.TimeoutExpired):
            problems.append(f"cannot verify locked {label}; inspect runtime permissions and browser dependencies")
    return problems
