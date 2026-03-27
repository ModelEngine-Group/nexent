import JSZip from "jszip";
import yaml from "js-yaml";
import type { SkillFileNode, ExtendedSkillFileNode } from "@/types/skill";
import React from "react";
import { FileTerminal, FileText, Folder, File } from "lucide-react";

export type { ExtendedSkillFileNode } from "@/types/skill";

/**
 * Result of extracting skill information from file content.
 */
export interface SkillInfo {
  name: string | null;
  description: string | null;
}

/**
 * Extract YAML frontmatter fields using js-yaml parser.
 */
const extractFrontmatter = (content: string): { name: string | null; description: string | null } => {
  const normalized = content.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  const frontmatterMatch = normalized.match(/^---\n([\s\S]*?)\n---/);
  if (!frontmatterMatch) return { name: null, description: null };

  const frontmatter = frontmatterMatch[1];

  const parsed = yaml.load(frontmatter) as Record<string, unknown> | null;
  if (!parsed || typeof parsed !== "object") {
    return { name: null, description: null };
  }

  const name = typeof parsed.name === "string" && parsed.name.trim() ? parsed.name.trim() : null;
  const description = typeof parsed.description === "string" && parsed.description.trim()
    ? parsed.description.trim()
    : null;

  return { name, description };
};

/**
 * Extract skill name and description from file content.
 */
const extractFromContent = (content: string): SkillInfo => {
  return extractFrontmatter(content);
};

/**
 * Extract skill name and description from a SKILL.md file.
 * @param file File object (.md or .zip)
 * @returns Extracted skill info or null
 */
export const extractSkillInfo = async (file: File): Promise<SkillInfo | null> => {
  try {
    if (file.name.toLowerCase().endsWith(".zip")) {
      return await extractFromZip(file);
    } else if (file.name.toLowerCase().endsWith(".md")) {
      return await extractFromMd(file);
    }
    return null;
  } catch (error) {
    console.warn("Failed to extract skill info from file:", error);
    return null;
  }
};

/**
 * Extract skill name and description from a SKILL.md file.
 */
const extractFromMd = async (file: File): Promise<SkillInfo | null> => {
  const content = await file.text();
  return extractFromContent(content);
};

/**
 * Extract skill name and description from a ZIP file by looking for SKILL.md inside.
 */
const extractFromZip = async (file: File): Promise<SkillInfo | null> => {
  let zip;
  try {
    zip = await JSZip.loadAsync(file);
  } catch {
    return null;
  }
  const normalizedNames: string[] = [];
  zip.forEach((relativePath) => normalizedNames.push(relativePath.replace(/\\/g, "/")));

  let skillMdPath: string | null = null;
  for (const name of normalizedNames) {
    if (name === "SKILL.md" || name === "skill.md") {
      skillMdPath = name;
      break;
    }
  }

  if (!skillMdPath) {
    for (const name of normalizedNames) {
      if (name.endsWith("/SKILL.md") || name.endsWith("/skill.md")) {
        skillMdPath = name;
        break;
      }
    }
  }

  if (!skillMdPath) return null;

  const content = await zip.file(skillMdPath)?.async("string");
  return content ? extractFromContent(content) : null;
};

/**
 * Extract skill name, description, tags and content (without frontmatter) from a string content.
 * This is used for parsing skill content from text (e.g., from temp files or AI responses).
 * @param content The raw content string containing frontmatter and/or SKILL block
 * @returns Extracted skill info including content without frontmatter
 */
export const extractSkillInfoFromContent = (content: string): { name: string; description: string; tags: string[]; contentWithoutFrontmatter: string } => {
  const result: { name: string; description: string; tags: string[]; contentWithoutFrontmatter: string } = {
    name: "",
    description: "",
    tags: [],
    contentWithoutFrontmatter: "",
  };

  if (!content) return result;

  const skillBlockMatch = content.match(/<SKILL>([\s\S]*?)<\/SKILL>/);
  const blockContent = skillBlockMatch ? skillBlockMatch[1] : content;

  const frontmatterMatch = blockContent.match(/^---\n([\s\S]*?)\n---/);
  if (frontmatterMatch) {
    const frontmatter = frontmatterMatch[1];
    const parsed = yaml.load(frontmatter) as Record<string, unknown>;
    if (parsed && typeof parsed === "object") {
      result.name = typeof parsed.name === "string" ? parsed.name.trim() : "";
      result.description = typeof parsed.description === "string" ? parsed.description.trim() : "";
      result.tags = Array.isArray(parsed.tags) ? parsed.tags.filter((t): t is string => typeof t === "string") : [];
    }
    // Extract content after frontmatter
    const frontmatterEnd = blockContent.indexOf("---");
    const secondDash = blockContent.indexOf("---", frontmatterEnd + 3);
    if (secondDash !== -1) {
      result.contentWithoutFrontmatter = blockContent.substring(secondDash + 3).trim();
    } else {
      result.contentWithoutFrontmatter = blockContent.substring(frontmatterEnd + 3).trim();
    }
  } else {
    result.contentWithoutFrontmatter = blockContent;
  }

  return result;
};

// ========== Skill Build Modal Methods ==========

/**
 * Parse <SKILL>...</SKILL> block from assistant message content.
 * @param content The content containing SKILL block
 * @returns Parsed skill draft or null if not found
 */
export const parseSkillDraft = (content: string): {
  name: string;
  description: string;
  tags: string[];
  content: string;
} | null => {
  const match = content.match(/<SKILL>([\s\S]*?)<\/SKILL>/);
  if (!match) return null;

  const skillBlock = match[1].trim();

  let tags: string[] = [];
  let description = "";
  let name = "";
  let contentWithoutFrontmatter = skillBlock;

  const frontmatterMatch = skillBlock.match(/^---\n([\s\S]*?)\n---/);
  if (frontmatterMatch) {
    const frontmatter = frontmatterMatch[1];
    const parsed = yaml.load(frontmatter) as Record<string, unknown>;
    if (parsed && typeof parsed === "object") {
      name = typeof parsed.name === "string" ? parsed.name.trim() : "";
      description = typeof parsed.description === "string" ? parsed.description.trim() : "";
      tags = Array.isArray(parsed.tags) ? parsed.tags.filter((t): t is string => typeof t === "string") : [];
    }
    // Remove frontmatter from content
    const frontmatterEnd = skillBlock.indexOf("---");
    const secondDash = skillBlock.indexOf("---", frontmatterEnd + 3);
    if (secondDash !== -1) {
      contentWithoutFrontmatter = skillBlock.substring(secondDash + 3).trim();
    } else {
      contentWithoutFrontmatter = skillBlock.substring(frontmatterEnd + 3).trim();
    }
  }

  if (!name && !description && !contentWithoutFrontmatter) return null;
  return { name, description, tags, content: contentWithoutFrontmatter };
};

/**
 * Extract content after </SKILL> tag for display.
 * @param content The full content string
 * @returns Content after </SKILL> tag
 */
export const extractSkillGenerationResult = (content: string): string => {
  const skillTagIndex = content.indexOf("</SKILL>");
  if (skillTagIndex !== -1) {
    return content.substring(skillTagIndex + 8).trim();
  }
  return content;
};

// ========== Skill Detail Modal Methods ==========

/**
 * Check if a filename is a markdown file.
 * @param filename The filename to check
 * @returns True if it's a markdown file
 */
export const isMarkdownFile = (filename: string): boolean => {
  return filename.endsWith(".md") || filename.endsWith(".mdx") || filename.endsWith(".markdown");
};

/**
 * Strip YAML frontmatter from SKILL.md content before rendering.
 * @param content The full file content
 * @returns Content without frontmatter
 */
export const stripFrontmatter = (content: string): string => {
  if (!content.startsWith("---")) {
    return content;
  }
  const endIndex = content.indexOf("---", 3);
  if (endIndex === -1) {
    return content;
  }
  return content.slice(endIndex + 3).trimStart();
};

/**
 * Extract the filename (last segment) from a path.
 * @param filePath The file path
 * @returns The filename or empty string
 */
export const getFileName = (filePath: string | null): string => {
  if (!filePath) return "";
  const parts = filePath.split("/");
  return parts[parts.length - 1] || "";
};

/**
 * Determine if the selected file is a SKILL.md file (case-insensitive).
 * @param filename The filename to check
 * @returns True if it's a SKILL.md file
 */
export const isSkillMdFile = (filename: string | null): boolean => {
  if (!filename) return false;
  return getFileName(filename).toLowerCase() === "skill.md";
};

/**
 * Normalize skill files data to array format.
 * @param data The raw data from API
 * @returns Normalized SkillFileNode array
 */
export const normalizeSkillFiles = (data: unknown): SkillFileNode[] => {
  const isSkillFileNodeArray = (d: unknown): d is SkillFileNode[] => {
    return Array.isArray(d);
  };

  if (isSkillFileNodeArray(data)) {
    return data;
  }
  if (data && typeof data === "object" && ("name" in data || "type" in data)) {
    return [data as SkillFileNode];
  }
  return [];
};

/**
 * Get the appropriate icon for a file based on its name and type.
 * @param name File name
 * @param type File type (file or directory)
 * @returns React icon component
 */
export const getFileIcon = (name: string, type: string): React.ReactNode => {
  if (type === "directory") {
    return <Folder size={14} className="text-amber-500" />;
  }
  const lower = name.toLowerCase();
  if (lower.endsWith(".md") || lower.endsWith(".mdx") || lower.endsWith(".markdown")) {
    return <FileText size={14} className="text-blue-500" />;
  }
  if (lower.endsWith(".sh") || lower.endsWith(".py")) {
    return <FileTerminal size={14} className="text-green-600" />;
  }
  return <File size={14} className="text-gray-400" />;
};

let nodeIdCounter = 0;

/**
 * Build tree data structure from skill files array.
 * @param files Array of skill file nodes
 * @param parentPath Parent path for nested files
 * @returns Extended data nodes for Ant Design Tree
 */
export const buildTreeData = (files: SkillFileNode[], parentPath: string = ""): ExtendedSkillFileNode[] => {
  if (!Array.isArray(files)) {
    console.warn("buildTreeData received non-array:", files);
    return [];
  }
  return files.map((file) => {
    nodeIdCounter++;
    const fullPath = parentPath ? `${parentPath}/${file.name}` : file.name;
    const uniqueKey = `${fullPath}__${file.type}__${nodeIdCounter}`;

    return {
      key: uniqueKey,
      title: file.name,
      icon: getFileIcon(file.name, file.type),
      isLeaf: file.type === "file",
      children: file.children ? buildTreeData(file.children, fullPath) : undefined,
      data: file,
      fullPath: fullPath,
    };
  });
};

/**
 * Find a node in the tree by its key.
 * @param nodes Tree nodes to search
 * @param key Key to find
 * @returns Found node or null
 */
export const findNodeByKey = (
  nodes: ExtendedSkillFileNode[],
  key: React.Key
): ExtendedSkillFileNode | null => {
  for (const node of nodes) {
    if (node.key === key) return node;
    if (node.children) {
      const found = findNodeByKey(node.children as ExtendedSkillFileNode[], key);
      if (found) return found;
    }
  }
  return null;
};

/**
 * Collect all directory keys from tree nodes for auto-expansion.
 * @param nodes Tree nodes to traverse
 * @returns Array of directory keys
 */
export const collectDirKeys = (nodes: ExtendedSkillFileNode[]): React.Key[] => {
  const keys: React.Key[] = [];
  for (const node of nodes) {
    if (node.children && (node.children as ExtendedSkillFileNode[]).length > 0) {
      keys.push(node.key);
      keys.push(...collectDirKeys(node.children as ExtendedSkillFileNode[]));
    }
  }
  return keys;
};

/**
 * Reset the node ID counter (call before rebuilding tree).
 */
export const resetNodeIdCounter = (): void => {
  nodeIdCounter = 0;
};
