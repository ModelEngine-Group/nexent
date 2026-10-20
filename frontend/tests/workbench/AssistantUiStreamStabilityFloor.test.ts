// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

/**
 * Regression guard for the streaming nested-update crash (React minified
 * error #185, "Maximum update depth exceeded").
 *
 * Bug: while the NL2Agent creation agent streamed long reasoning output (for
 * example the "recommend available resources" suggestion), the newchat page
 * crashed through the root error boundary. The user's console stack ended in
 * `setRef -> ... -> Object.dispatchUpdate -> <react-dom>`, i.e. a ref callback
 * re-attached during commit synchronously dispatched a store update, and the
 * nested update chain never settled. The app's own `useAuiState` selectors
 * return stable primitives/references (audited), and the adapter keeps parts
 * append-only (see StreamPartsIndexStability.test.ts), so the loop lived in
 * the @assistant-ui runtime stack itself.
 *
 * The fixes are upstream patch releases. This test pins the minimum versions
 * that contain them so a lockfile refresh can never silently drop the app
 * back onto the crash-prone line:
 *
 * - @assistant-ui/react >= 0.15.25
 *     #8684 (0.15.24) keys message parts by host identity instead of raw
 *       array index, and
 *     #8760 (0.15.25) removes wall-clock reads during render, which tap's
 *       commit-time snapshot re-check treats as an ever-changing value.
 * - @assistant-ui/core >= 0.3.22
 *     #8504 stops a reloading running thread from notifying store subscribers
 *       during render, the direct nested-update source.
 * - @assistant-ui/store >= 0.3.18
 *     #9003 keeps thread viewport observers referentially stable (unstable
 *       observer refs re-attach on every commit and dispatch from the ref
 *       callback, the `setRef` frame in the crash stack), and
 *     #9094 wakes only the selectors whose clients changed, so a streaming
 *       token no longer re-runs every message/part selector.
 * - @assistant-ui/tap >= 0.9.22
 *     #8441 makes flushTapSync run only the tasks queued in its own flush,
 *       so a corrective update no longer commits inside another root's flush.
 *
 * The floors assert the resolved (installed) packages, not the package.json
 * ranges: what the bundler actually ships is what crashes or does not.
 */

import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { createRequire } from "node:module";
import { describe, expect, it } from "vitest";

const require = createRequire(import.meta.url);

/** Parse the leading numeric `major.minor.patch` triple of a version string. */
function parseVersion(version: string): [number, number, number] {
  const match = /^(\d+)\.(\d+)\.(\d+)/.exec(version.trim());
  if (!match) {
    throw new Error(`Cannot parse semantic version from "${version}"`);
  }
  return [
    Number.parseInt(match[1] ?? "", 10),
    Number.parseInt(match[2] ?? "", 10),
    Number.parseInt(match[3] ?? "", 10),
  ];
}

/** True when `version` is at or above `floor` (numeric triple comparison). */
function versionGte(version: string, floor: string): boolean {
  const parsed = parseVersion(version);
  const parsedFloor = parseVersion(floor);
  for (let i = 0; i < 3; i += 1) {
    if ((parsed[i] ?? 0) !== (parsedFloor[i] ?? 0)) {
      return (parsed[i] ?? 0) > (parsedFloor[i] ?? 0);
    }
  }
  return true;
}

/**
 * Resolve the installed version of a package by walking up from its resolved
 * entry point to its package.json. Reading the package.json through the
 * resolver (instead of `require(pkg + "/package.json")`) keeps working for
 * packages whose `exports` map does not expose `./package.json`.
 */
function installedVersion(pkg: string): string {
  const entryPath = require.resolve(pkg);
  let dir = dirname(entryPath);
  for (let depth = 0; depth < 10; depth += 1) {
    const manifestPath = join(dir, "package.json");
    if (existsSync(manifestPath)) {
      const manifest = JSON.parse(readFileSync(manifestPath, "utf8")) as {
        name?: string;
        version?: string;
      };
      if (manifest.name === pkg && manifest.version) {
        return manifest.version;
      }
    }
    const parent = dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  throw new Error(
    `Could not locate package.json for "${pkg}" above ${entryPath}`
  );
}

const STREAM_STABILITY_FLOORS: ReadonlyArray<{
  pkg: string;
  floor: string;
  fix: string;
}> = [
  {
    pkg: "@assistant-ui/react",
    floor: "0.15.25",
    fix: "part identity keys (#8684) and no wall-clock reads during render (#8760)",
  },
  {
    pkg: "@assistant-ui/core",
    floor: "0.3.22",
    fix: "reloading a running thread no longer notifies store subscribers during render (#8504)",
  },
  {
    pkg: "@assistant-ui/store",
    floor: "0.3.18",
    fix: "stable viewport observers (#9003) and per-client selector wake scoping (#9094)",
  },
  {
    pkg: "@assistant-ui/tap",
    floor: "0.9.22",
    fix: "flushTapSync no longer flushes another root's queued update (#8441)",
  },
];

describe("assistant-ui streaming stability dependency floors", () => {
  it.each(STREAM_STABILITY_FLOORS)(
    "$pkg is installed at >= $floor ($fix)",
    ({ pkg, floor, fix }) => {
      const version = installedVersion(pkg);
      expect(
        versionGte(version, floor),
        `${pkg}@${version} is below the streaming-stability floor ${floor} (${fix}); ` +
          "regenerate frontend/package-lock.json after bumping @assistant-ui/react"
      ).toBe(true);
    }
  );

  it("resolves a version for every floored package", () => {
    for (const { pkg } of STREAM_STABILITY_FLOORS) {
      expect(() => installedVersion(pkg)).not.toThrow();
    }
  });
});
