"use client";

import type {
  Unstable_DirectiveFormatter,
  Unstable_DirectiveSegment,
  Unstable_TriggerItem,
} from "@assistant-ui/react";
import { unstable_defaultDirectiveFormatter } from "@assistant-ui/react";
import { FolderSymlink, SquareCode, type LucideIcon } from "lucide-react";

export const SKILL_SCRIPT_DIRECTIVE_TYPE = "skill-script";
export const SKILL_REFERENCE_DIRECTIVE_TYPE = "skill-reference";

export interface XmlDirectiveDefinition {
  tagName: string;
  type: string;
  requiredAttributes: readonly string[];
  icon: LucideIcon;
  labelAttribute: string;
}

export interface ParsedXmlDirective {
  definition: XmlDirectiveDefinition;
  attributes: Readonly<Record<string, string>>;
  raw: string;
}

export const skillDirectiveDefinitions = [
  {
    tagName: "use_script",
    type: SKILL_SCRIPT_DIRECTIVE_TYPE,
    requiredAttributes: ["path"],
    icon: SquareCode,
    labelAttribute: "path",
  },
  {
    tagName: "reference",
    type: SKILL_REFERENCE_DIRECTIVE_TYPE,
    requiredAttributes: ["path"],
    icon: FolderSymlink,
    labelAttribute: "path",
  },
] as const satisfies readonly XmlDirectiveDefinition[];

const XML_ATTRIBUTE_PATTERN = /([A-Za-z_:][\w:.-]*)\s*=\s*(["'])([\s\S]*?)\2/g;

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function decodeXmlAttribute(value: string): string {
  return value
    .replaceAll("&quot;", '"')
    .replaceAll("&apos;", "'")
    .replaceAll("&lt;", "<")
    .replaceAll("&gt;", ">")
    .replaceAll("&amp;", "&");
}

function escapeXmlAttribute(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll('"', "&quot;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

export function normalizeSkillDirectivePath(value: string): string | null {
  const path = value.trim().replaceAll("\\", "/");
  if (!path || path.includes("\0") || path.startsWith("/")) return null;
  if (/^[A-Za-z]:\//.test(path)) return null;

  const segments = path.split("/");
  if (segments.some((segment) => !segment || segment === "..")) return null;
  return segments.filter((segment) => segment !== ".").join("/");
}

function parseAttributes(source: string): Record<string, string> | null {
  const attributes: Record<string, string> = {};
  let cursor = 0;
  XML_ATTRIBUTE_PATTERN.lastIndex = 0;

  for (const match of source.matchAll(XML_ATTRIBUTE_PATTERN)) {
    const index = match.index ?? 0;
    if (source.slice(cursor, index).trim()) return null;

    const name = match[1];
    if (!name || Object.hasOwn(attributes, name)) return null;
    attributes[name] = decodeXmlAttribute(match[3] ?? "");
    cursor = index + match[0].length;
  }

  if (source.slice(cursor).trim()) return null;
  return attributes;
}

export function parseXmlDirective(
  raw: string,
  definitions: readonly XmlDirectiveDefinition[] = skillDirectiveDefinitions
): ParsedXmlDirective | null {
  for (const definition of definitions) {
    const pattern = new RegExp(
      `^<${escapeRegExp(definition.tagName)}\\b([\\s\\S]*?)\\/\\s*>$`
    );
    const match = raw.match(pattern);
    if (!match) continue;

    const attributes = parseAttributes(match[1] ?? "");
    if (!attributes) return null;
    if (
      definition.requiredAttributes.some(
        (attribute) => !attributes[attribute]?.trim()
      )
    ) {
      return null;
    }

    if (attributes.path !== undefined) {
      const normalizedPath = normalizeSkillDirectivePath(attributes.path);
      if (!normalizedPath) return null;
      attributes.path = normalizedPath;
    }

    return { definition, attributes, raw };
  }
  return null;
}

function basename(path: string): string {
  return path.split("/").at(-1) || path;
}

export function createXmlDirectiveFormatter(
  definitions: readonly XmlDirectiveDefinition[]
): Unstable_DirectiveFormatter {
  const definitionByType = new Map(
    definitions.map((definition) => [definition.type, definition])
  );
  const tagNames = definitions.map((definition) =>
    escapeRegExp(definition.tagName)
  );
  const directivePattern = new RegExp(
    `<(?:${tagNames.join("|")})\\b[\\s\\S]*?\\/\\s*>`,
    "g"
  );

  return {
    serialize(item: Unstable_TriggerItem): string {
      const definition = definitionByType.get(item.type);
      if (!definition) return item.label;
      const path = normalizeSkillDirectivePath(item.id);
      if (!path) return item.label;
      return `<${definition.tagName} path="${escapeXmlAttribute(path)}" />`;
    },
    parse(text: string): readonly Unstable_DirectiveSegment[] {
      const segments: Unstable_DirectiveSegment[] = [];
      let cursor = 0;
      directivePattern.lastIndex = 0;

      for (const match of text.matchAll(directivePattern)) {
        const index = match.index ?? 0;
        const parsed = parseXmlDirective(match[0], definitions);
        if (!parsed) continue;

        if (index > cursor) {
          segments.push({ kind: "text", text: text.slice(cursor, index) });
        }
        const id = parsed.attributes[parsed.definition.labelAttribute] ?? "";
        segments.push({
          kind: "mention",
          type: parsed.definition.type,
          id,
          label: basename(id),
        });
        cursor = index + match[0].length;
      }

      if (cursor < text.length) {
        segments.push({ kind: "text", text: text.slice(cursor) });
      }
      return segments.length > 0 ? segments : [{ kind: "text", text }];
    },
  };
}

export const skillDirectiveFormatter = createXmlDirectiveFormatter(
  skillDirectiveDefinitions
);

export const combinedSkillDirectiveFormatter: Unstable_DirectiveFormatter = {
  serialize(item) {
    if (
      item.type === SKILL_SCRIPT_DIRECTIVE_TYPE ||
      item.type === SKILL_REFERENCE_DIRECTIVE_TYPE
    ) {
      return skillDirectiveFormatter.serialize(item);
    }
    return unstable_defaultDirectiveFormatter.serialize(item);
  },
  parse(text) {
    return skillDirectiveFormatter
      .parse(text)
      .flatMap((segment) =>
        segment.kind === "text"
          ? unstable_defaultDirectiveFormatter.parse(segment.text)
          : [segment]
      );
  },
};

export const skillDirectiveIconMap = {
  [SKILL_SCRIPT_DIRECTIVE_TYPE]: SquareCode,
  [SKILL_REFERENCE_DIRECTIVE_TYPE]: FolderSymlink,
} satisfies Record<string, LucideIcon>;

export function isSkillDirectiveHtml(value: string): boolean {
  return skillDirectiveFormatter
    .parse(value)
    .some((segment) => segment.kind === "mention");
}

/**
 * Escape valid skill directive tags before Markdown parsing so they become
 * text nodes instead of custom HTML elements. The renderer can then turn the
 * text nodes into DirectiveText chips without rehype consuming the tags.
 */
export function escapeSkillDirectivesForMarkdown(value: string): string {
  const tagNames = skillDirectiveDefinitions.map((definition) =>
    escapeRegExp(definition.tagName)
  );
  const candidatePattern = new RegExp(
    `<(?:${tagNames.join("|")})\\b[\\s\\S]*?\\/\\s*>`,
    "g"
  );

  return value.replace(candidatePattern, (candidate) => {
    if (!parseXmlDirective(candidate)) return candidate;
    return candidate.replaceAll("<", "&lt;").replaceAll(">", "&gt;");
  });
}

function isSkillDirectiveCandidateHtml(value: string): boolean {
  return skillDirectiveDefinitions.some((definition) =>
    new RegExp(
      `^<${escapeRegExp(definition.tagName)}\\b[\\s\\S]*?\\/\\s*>$`
    ).test(value)
  );
}

export function remarkSkillXmlDirectives() {
  return (tree: { children?: unknown[] }) => {
    const visitNode = (node: unknown, parentType?: string) => {
      if (!node || typeof node !== "object") return;
      const typedNode = node as {
        type?: string;
        value?: string;
        children?: unknown[];
      };
      if (
        typedNode.type === "html" &&
        typeof typedNode.value === "string" &&
        isSkillDirectiveCandidateHtml(typedNode.value)
      ) {
        if (
          parentType === "root" ||
          parentType === "blockquote" ||
          parentType === "listItem"
        ) {
          typedNode.type = "paragraph";
          typedNode.children = [{ type: "text", value: typedNode.value }];
          delete typedNode.value;
        } else {
          typedNode.type = "text";
        }
      }
      typedNode.children?.forEach((child) => visitNode(child, typedNode.type));
    };
    visitNode(tree);
  };
}
