import React from "react";
import remarkParse from "remark-parse";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import { visit } from "unist-util-visit";

export interface MarkdownHeading {
  id: string;
  level: number;
  text: string;
}

export interface ParsedMarkdownHeading extends MarkdownHeading {
  offset: number;
}

export const flattenTextContent = (value: React.ReactNode): string => {
  if (typeof value === "string" || typeof value === "number") {
    return String(value);
  }
  if (Array.isArray(value)) return value.map(flattenTextContent).join("");
  if (React.isValidElement(value)) {
    return flattenTextContent(value.props?.children);
  }
  return "";
};

export const normalizeMarkdownHeadingText = (value: string): string =>
  value
    .replaceAll("`", "")
    .replaceAll("<", "")
    .replaceAll(">", "")
    .replaceAll("*", "")
    .replaceAll("_", "")
    .replaceAll("~", "")
    .replaceAll("\\", "")
    .replaceAll(/\s+/g, " ")
    .trim();

export const slugifyHeadingText = (value: string): string => {
  const normalized = normalizeMarkdownHeadingText(value)
    .toLowerCase()
    .replaceAll(/[^a-z0-9\u4e00-\u9fa5\s-]/g, "")
    .trim()
    .replaceAll(/\s+/g, "-");
  return normalized || "section";
};

const createHeadingIdGenerator = () => {
  const counts = new Map<string, number>();
  return (text: string) => {
    const baseId = slugifyHeadingText(text);
    const count = counts.get(baseId) ?? 0;
    counts.set(baseId, count + 1);
    return count === 0 ? baseId : `${baseId}-${count}`;
  };
};

const extractTextFromMarkdownNode = (node: any): string => {
  if (!node) return "";
  if (typeof node.value === "string") return node.value;
  if (Array.isArray(node.children)) {
    return node.children.map(extractTextFromMarkdownNode).join("");
  }
  return "";
};

const extractFallbackMarkdownHeadings = (
  content: string
): ParsedMarkdownHeading[] => {
  const createId = createHeadingIdGenerator();
  const headings: ParsedMarkdownHeading[] = [];
  let offset = 0;
  for (const line of content.split("\n")) {
    const trimmedLine = line.trimStart();
    const leadingSpaces = line.length - trimmedLine.length;
    if (!trimmedLine.startsWith("#")) {
      offset += line.length + 1;
      continue;
    }
    let level = 0;
    while (level < trimmedLine.length && trimmedLine[level] === "#") level += 1;
    if (level >= 1 && level <= 6 && trimmedLine[level] === " ") {
      const text = normalizeMarkdownHeadingText(trimmedLine.slice(level + 1));
      if (!text) {
        offset += line.length + 1;
        continue;
      }
      headings.push({
        id: createId(text),
        level,
        text,
        offset: offset + leadingSpaces,
      });
    }
    offset += line.length + 1;
  }
  return headings;
};

export const extractParsedMarkdownHeadings = (
  content: string
): ParsedMarkdownHeading[] => {
  try {
    const createId = createHeadingIdGenerator();
    const headings: ParsedMarkdownHeading[] = [];
    const { unified } = require("unified") as { unified: () => any };
    const tree = unified()
      .use(remarkParse)
      .use(remarkGfm)
      .use(remarkMath)
      .parse(content);
    visit(tree, "heading", (node: any) => {
      const text = normalizeMarkdownHeadingText(
        extractTextFromMarkdownNode(node)
      );
      if (!text) return;
      headings.push({
        id: createId(text),
        level: Number(node.depth) || 1,
        text,
        offset:
          typeof node.position?.start?.offset === "number"
            ? node.position.start.offset
            : headings.length,
      });
    });
    return headings;
  } catch {
    return extractFallbackMarkdownHeadings(content);
  }
};

export const extractMarkdownHeadings = (content: string): MarkdownHeading[] =>
  extractParsedMarkdownHeadings(content).map(({ id, level, text }) => ({
    id,
    level,
    text,
  }));
