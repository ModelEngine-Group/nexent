import { existsSync } from "node:fs";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import openapiTS, { astToString } from "openapi-typescript";
import { format } from "prettier";

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const sourcePath = resolve(
  frontendRoot,
  "../contracts/nl2agent-card.schema.json"
);
const targetPath = resolve(
  frontendRoot,
  "contracts/generated/nl2agent-card.schema.json"
);
const repositoryRoot = resolve(frontendRoot, "..");
const openapiSourcePath = resolve(
  repositoryRoot,
  "contracts/nl2agent-openapi.json"
);
const apiTypesTargetPath = resolve(
  frontendRoot,
  "contracts/generated/nl2agent-api.ts"
);
const backendPythonCandidates = [
  process.env.NEXENT_BACKEND_PYTHON,
  resolve(repositoryRoot, "backend/.venv/Scripts/python.exe"),
  resolve(repositoryRoot, "backend/.venv/bin/python"),
].filter(Boolean);
const backendPython = backendPythonCandidates.find(existsSync);
if (!backendPython) {
  throw new Error(
    "Backend virtualenv Python is required for contract generation."
  );
}
const checkMode = process.argv.includes("--check");
const temporaryDirectory = checkMode
  ? await mkdtemp(resolve(tmpdir(), "nexent-nl2agent-contracts-"))
  : undefined;
const exportedOpenapiPath = temporaryDirectory
  ? resolve(temporaryDirectory, "nl2agent-openapi.json")
  : openapiSourcePath;
const exportedCardPath = temporaryDirectory
  ? resolve(temporaryDirectory, "nl2agent-card.schema.json")
  : sourcePath;
const exportArguments = [
  resolve(repositoryRoot, "backend/scripts/export_nl2agent_openapi.py"),
  "--output",
  exportedOpenapiPath,
  "--card-output",
  exportedCardPath,
];
const exportResult = spawnSync(backendPython, exportArguments, {
  cwd: repositoryRoot,
  encoding: "utf8",
});
if (exportResult.status !== 0) {
  throw new Error(
    exportResult.stderr ||
      exportResult.stdout ||
      "Failed to export NL2AGENT OpenAPI."
  );
}
const source = await format(await readFile(exportedCardPath, "utf8"), {
  parser: "json",
});
const openapiSourceText = await format(
  await readFile(exportedOpenapiPath, "utf8"),
  { parser: "json" }
);

if (checkMode) {
  const canonicalSource = await readFile(sourcePath, "utf8").catch(() => "");
  if (canonicalSource !== source) {
    throw new Error(
      "Canonical NL2AGENT card schema is out of date. Run pnpm contracts:generate."
    );
  }
  const canonicalOpenapi = await readFile(openapiSourcePath, "utf8").catch(
    () => ""
  );
  if (canonicalOpenapi !== openapiSourceText) {
    throw new Error(
      "Canonical NL2AGENT OpenAPI is out of date. Run pnpm contracts:generate."
    );
  }
  const target = await readFile(targetPath, "utf8").catch(() => "");
  if (target !== source) {
    throw new Error(
      "Generated NL2AGENT card schema is out of date. Run pnpm contracts:generate."
    );
  }
} else {
  await writeFile(sourcePath, source, "utf8");
  await writeFile(openapiSourcePath, openapiSourceText, "utf8");
  await mkdir(dirname(targetPath), { recursive: true });
  await writeFile(targetPath, source, "utf8");
}
const openapiSource = JSON.parse(openapiSourceText);
const apiTypes = await format(
  astToString(await openapiTS(openapiSource, { defaultNonNullable: false })),
  { parser: "typescript" }
);
if (checkMode) {
  const target = await readFile(apiTypesTargetPath, "utf8").catch(() => "");
  if (target !== apiTypes) {
    throw new Error(
      "Generated NL2AGENT API types are out of date. Run pnpm contracts:generate."
    );
  }
} else {
  await mkdir(dirname(apiTypesTargetPath), { recursive: true });
  await writeFile(apiTypesTargetPath, apiTypes, "utf8");
}
if (temporaryDirectory) {
  await rm(temporaryDirectory, { recursive: true, force: true });
}
