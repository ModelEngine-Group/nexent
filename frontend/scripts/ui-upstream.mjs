// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import prettier from "prettier";
import { frontendRoot, importsIn } from "./ui-boundaries.mjs";

export const digest = (value) =>
  crypto.createHash("sha256").update(value).digest("hex");
const read = (file) => fs.readFileSync(file, "utf8");
const manifestFile = (root) => path.join(root, "vendor/shadcn/manifest.json");
const header =
  "// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.\n\n";

function inside(root, relative) {
  const result = path.resolve(root, relative);
  if (!result.startsWith(path.resolve(root) + path.sep))
    throw new Error(`Path escapes its root: ${relative}`);
  return result;
}

function validateRadix(source, root) {
  const imports = importsIn(source);
  if (
    imports.some(({ specifier }) =>
      /^(?:@base-ui(?:-components)?\/|@radix-ui\/themes|@\/registry\/bases\/base)/.test(
        specifier
      )
    )
  ) {
    throw new Error("Candidate includes an unsupported component base");
  }
  if (
    imports.some(
      ({ specifier }) =>
        specifier === "cn" || specifier.startsWith("@/registry/")
    )
  ) {
    throw new Error("Candidate contains unresolved registry imports");
  }
  if (root && fs.existsSync(path.join(root, "package.json"))) {
    const pkg = JSON.parse(read(path.join(root, "package.json")));
    const declared = { ...pkg.dependencies, ...pkg.devDependencies };
    for (const { specifier } of imports) {
      if (specifier.startsWith("@/")) {
        if (
          specifier !== "@/lib/utils" &&
          !specifier.startsWith("@/components/ui/")
        )
          throw new Error(`Unexpected basic UI dependency: ${specifier}`);
        const target = inside(root, specifier.slice(2));
        if (
          !["", ".ts", ".tsx", "/index.ts", "/index.tsx"].some((extension) =>
            fs.existsSync(target + extension)
          )
        )
          throw new Error(`Missing local dependency: ${specifier}`);
      } else if (!specifier.startsWith(".")) {
        const name = specifier
          .split("/")
          .slice(0, specifier.startsWith("@") ? 2 : 1)
          .join("/");
        if (!declared[name])
          throw new Error(
            `Review and declare new upstream dependency: ${name}`
          );
      }
    }
  }
}

export async function transformSource(raw, name, root = frontendRoot) {
  let source =
    header +
    raw
      .replace(
        /^\/\/ Copyright \(c\) 2025-2026 Huawei Technologies Co\., Ltd\. All rights reserved\.\r?\n\r?\n/,
        ""
      )
      .replaceAll('from "cn"', 'from "@/lib/utils"')
      .replaceAll("@/registry/new-york-v4/ui/", "@/components/ui/")
      .replaceAll(
        "@/registry/new-york-v4/hooks/use-mobile",
        "@/components/ui/use-mobile"
      );
  validateRadix(source, root);
  return prettier.format(source, {
    ...(await prettier.resolveConfig(path.join(root, ".prettierrc"))),
    parser: "typescript",
    endOfLine: "lf",
  });
}

export function mergeSources(local, base, next) {
  // git merge-file requires files. Its caller supplies isolated candidate paths.
  try {
    return {
      source: execFileSync(
        "git",
        ["merge-file", "-p", "--", local, base, next],
        { encoding: "utf8", maxBuffer: 10 * 1024 * 1024 }
      ),
      conflicted: false,
    };
  } catch (error) {
    if (
      error.status > 0 &&
      error.status <= 127 &&
      error.stdout?.includes("<<<<<<<")
    )
      return { source: error.stdout, conflicted: true };
    throw error;
  }
}

export async function prepareCandidate({
  root = frontendRoot,
  name,
  commit,
  output,
  fetchSource,
}) {
  if (!/^[a-f0-9]{40}$/.test(commit ?? ""))
    throw new Error("Specify an immutable 40-character upstream commit");
  if (!output || !path.isAbsolute(output))
    throw new Error("Specify an absolute isolated --output directory");
  const relative = path.relative(root, output);
  if (
    !relative.startsWith(".." + path.sep) &&
    relative !== ".." &&
    !path.isAbsolute(relative)
  )
    throw new Error("Candidate directory must be outside the frontend tree");
  const manifest = JSON.parse(read(manifestFile(root)));
  const entry = manifest.components[name];
  if (!entry || entry.provenance !== "verified")
    throw new Error(
      "Unknown upstream ancestor; review and establish a baseline first"
    );
  if (
    !/^apps\/v4\/registry\/new-york-v4\/(?:ui\/[a-z-]+\.tsx|hooks\/use-mobile\.ts)$/.test(
      entry.sourcePath
    ) ||
    entry.transform !== "radix-new-york-v4-v2"
  )
    throw new Error(
      "Unsupported source or transform; review the generator contract first"
    );
  const raw = fetchSource
    ? await fetchSource(commit, entry.sourcePath)
    : await (async () => {
        const response = await fetch(
          `https://raw.githubusercontent.com/shadcn-ui/ui/${commit}/${entry.sourcePath}`,
          { signal: AbortSignal.timeout(30000) }
        );
        if (!response.ok)
          throw new Error(`Upstream fetch failed: ${response.status}`);
        return response.text();
      })();
  const generated = await transformSource(raw, name, root);
  const vendor = path.dirname(manifestFile(root));
  const base = read(inside(vendor, entry.generatedBaseline));
  const oldRaw = read(inside(vendor, entry.rawBaseline));
  if (
    digest(oldRaw) !== entry.rawSha256 ||
    digest(base) !== entry.generatedSha256
  )
    throw new Error("Stored upstream baseline hash mismatch");
  const current = read(inside(root, entry.target));
  fs.mkdirSync(path.dirname(output), { recursive: true });
  fs.mkdirSync(output); // Never reuse or overwrite an existing candidate directory.
  const files = {
    "local.txt": current,
    "base.txt": base,
    "generated.txt": generated,
    "raw.txt": raw,
  };
  for (const [file, source] of Object.entries(files))
    fs.writeFileSync(path.join(output, file), source);
  const merged = mergeSources(
    path.join(output, "local.txt"),
    path.join(output, "base.txt"),
    path.join(output, "generated.txt")
  );
  fs.writeFileSync(path.join(output, "merged.tsx"), merged.source);
  const candidate = {
    name,
    commit,
    entryHash: digest(JSON.stringify(entry)),
    localHash: digest(current),
    rawHash: digest(raw),
    generatedHash: digest(generated),
    configHash: digest(read(path.join(root, "components.json"))),
    conflicted: merged.conflicted,
  };
  fs.writeFileSync(
    path.join(output, "candidate.json"),
    JSON.stringify(candidate, null, 2) + "\n"
  );
  return candidate;
}

export async function acceptCandidate({
  root = frontendRoot,
  directory,
  reviewed = false,
  resolved = false,
}) {
  if (!reviewed)
    throw new Error("Review merged.tsx and pass --reviewed before accepting");
  const candidate = JSON.parse(read(path.join(directory, "candidate.json")));
  const manifest = JSON.parse(read(manifestFile(root)));
  const entry = manifest.components[candidate.name];
  if (!/^[a-f0-9]{40}$/.test(candidate.commit ?? ""))
    throw new Error("Candidate commit must remain immutable");
  if (!entry || candidate.entryHash !== digest(JSON.stringify(entry)))
    throw new Error("Manifest changed since preview");
  const target = inside(root, entry.target);
  const adopted = path.dirname(manifestFile(root));
  if (
    digest(read(inside(adopted, entry.rawBaseline))) !== entry.rawSha256 ||
    digest(read(inside(adopted, entry.generatedBaseline))) !==
      entry.generatedSha256
  )
    throw new Error("Stored baseline changed since preview");
  if (
    digest(read(target)) !== candidate.localHash ||
    digest(read(path.join(root, "components.json"))) !== candidate.configHash
  )
    throw new Error("Working source or configuration changed since preview");
  const raw = read(path.join(directory, "raw.txt"));
  const generated = await transformSource(raw, candidate.name, root);
  if (
    digest(raw) !== candidate.rawHash ||
    digest(generated) !== candidate.generatedHash
  )
    throw new Error("Candidate source or transform changed");
  const merged = read(path.join(directory, "merged.tsx"));
  if (
    (candidate.conflicted && !resolved) ||
    /^(?:<<<<<<<|=======|>>>>>>>)/m.test(merged)
  )
    throw new Error("Resolve conflicts and pass --resolved before accepting");
  validateRadix(merged, root);
  const vendor = path.dirname(manifestFile(root));
  const changes = new Map([
    [target, merged],
    [inside(vendor, entry.rawBaseline), raw],
    [inside(vendor, entry.generatedBaseline), generated],
  ]);
  Object.assign(entry, {
    commit: candidate.commit,
    rawSha256: digest(raw),
    generatedSha256: digest(generated),
  });
  changes.set(manifestFile(root), JSON.stringify(manifest, null, 2) + "\n");
  const backups = new Map(
    [...changes.keys()].map((file) => [file, read(file)])
  );
  try {
    for (const [file, contents] of changes) fs.writeFileSync(file, contents);
  } catch (error) {
    for (const [file, contents] of backups) fs.writeFileSync(file, contents);
    throw error;
  }
  return { component: candidate.name, commit: candidate.commit };
}

export function upstreamStatus(root = frontendRoot) {
  const manifest = JSON.parse(read(manifestFile(root)));
  const vendor = path.dirname(manifestFile(root));
  return Object.entries(manifest.components).map(([name, entry]) => {
    if (entry.provenance !== "verified")
      return { name, provenance: entry.provenance };
    const baseline = read(inside(vendor, entry.generatedBaseline));
    if (
      digest(baseline) !== entry.generatedSha256 ||
      digest(read(inside(vendor, entry.rawBaseline))) !== entry.rawSha256
    )
      throw new Error(`${name}: baseline hash mismatch`);
    return {
      name,
      provenance: "verified",
      commit: entry.commit,
      locallyModified:
        digest(read(inside(root, entry.target))) !== digest(baseline),
    };
  });
}

if (
  process.argv[1] &&
  path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  const [command, ...args] = process.argv.slice(2);
  const option = (key) => args[args.indexOf(key) + 1];
  try {
    let result;
    if (command === "status") result = upstreamStatus();
    else if (command === "preview")
      result = await prepareCandidate({
        name: args[0],
        commit: option("--ref"),
        output: option("--output"),
      });
    else if (command === "accept")
      result = await acceptCandidate({
        directory: args[0],
        reviewed: args.includes("--reviewed"),
        resolved: args.includes("--resolved"),
      });
    else
      throw new Error(
        "Usage: ui-upstream.mjs status | preview <name> --ref <commit> --output <absolute-dir> | accept <candidate-dir> --reviewed [--resolved]"
      );
    process.stdout.write(JSON.stringify(result, null, 2) + "\n");
  } catch (error) {
    process.stderr.write(error.message + "\n");
    process.exitCode = 1;
  }
}
