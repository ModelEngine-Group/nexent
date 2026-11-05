// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

export const frontendRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  ".."
);
const ignored = new Set([
  "node_modules",
  ".next",
  "vendor",
  "coverage",
  "dist",
]);
const legacy = /^(antd(?:\/|$)|antd-style(?:\/|$)|@ant-design\/icons(?:\/|$))/;
const otherBase = /^(?:@base-ui(?:-components)?\/|@radix-ui\/themes(?:\/|$))/;

export function sourceFiles(root) {
  const files = [];
  function visit(dir) {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      if (ignored.has(entry.name) || entry.isSymbolicLink()) continue;
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) visit(full);
      else if (/\.(?:[cm]?[jt]sx?)$/.test(entry.name)) files.push(full);
    }
  }
  visit(root);
  return files.sort();
}

export function importsIn(source, file = "component.tsx") {
  const ast = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true);
  const imports = [];
  function visit(node) {
    if (
      (ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) &&
      node.moduleSpecifier &&
      ts.isStringLiteral(node.moduleSpecifier)
    ) {
      const specifier = node.moduleSpecifier.text;
      const bindings = node.importClause?.namedBindings;
      const named =
        bindings && ts.isNamedImports(bindings)
          ? bindings
          : node.exportClause && ts.isNamedExports(node.exportClause)
            ? node.exportClause
            : null;
      const members = named
        ? named.elements.map((item) => (item.propertyName ?? item.name).text)
        : ["*"];
      if (node.importClause?.name) members.push("default");
      imports.push({ specifier, members: [...new Set(members)].sort() });
    }
    if (
      ts.isCallExpression(node) &&
      (node.expression.kind === ts.SyntaxKind.ImportKeyword ||
        node.expression.getText(ast) === "require") &&
      node.arguments[0] &&
      ts.isStringLiteral(node.arguments[0])
    ) {
      imports.push({ specifier: node.arguments[0].text, members: ["*"] });
    }
    ts.forEachChild(node, visit);
  }
  visit(ast);
  return imports;
}

export function inspectBoundaries(root) {
  const legacyImports = {};
  const violations = [];
  for (const file of sourceFiles(root)) {
    const relative = path.relative(root, file).split(path.sep).join("/");
    // Tests may exercise legacy behavior but must not become production exceptions.
    const test =
      /(^|\/)(tests?|e2e|__tests__)\//.test(relative) ||
      /\.(test|spec)\./.test(relative);
    const ui = relative.startsWith("components/ui/");
    for (const { specifier, members } of importsIn(
      fs.readFileSync(file, "utf8"),
      file
    )) {
      if (legacy.test(specifier) && !test) {
        if (
          relative.startsWith("components/common/") ||
          relative.startsWith("components/shared/")
        )
          violations.push(
            `${relative}: common components must not depend on ${specifier}`
          );
        legacyImports[relative] ??= [];
        legacyImports[relative].push(
          ...members.map((member) => `${specifier}:${member}`)
        );
      }
      if (otherBase.test(specifier) && !test)
        violations.push(`${relative}: unsupported base ${specifier}`);
      if (!ui) continue;
      const resolved = specifier.startsWith("@/")
        ? specifier.slice(2)
        : specifier.startsWith(".")
          ? path
              .relative(root, path.resolve(path.dirname(file), specifier))
              .split(path.sep)
              .join("/")
          : null;
      if (
        legacy.test(specifier) ||
        (resolved &&
          /^(?:app|features|ext_components|services|stores)\//.test(
            resolved
          )) ||
        resolved?.startsWith("components/common/")
      ) {
        violations.push(
          `${relative}: basic UI must not depend on ${specifier}`
        );
      }
    }
  }
  for (const file of Object.keys(legacyImports))
    legacyImports[file] = [...new Set(legacyImports[file])].sort();
  return { legacyImports, violations };
}

export function checkBoundaries(root) {
  return inspectBoundaries(root);
}

if (
  process.argv[1] &&
  path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  const result = checkBoundaries(frontendRoot);
  if (result.violations.length) {
    process.stderr.write(result.violations.join("\n") + "\n");
    process.exitCode = 1;
  } else
    process.stdout.write(
      `UI boundaries passed; ${Object.keys(result.legacyImports).length} files still import legacy UI.\n`
    );
}
