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
 * Falls back to regex extraction if yaml.load fails or returns invalid result.
 */
const extractFrontmatter = (content: string): { name: string | null; description: string | null } => {
  const normalized = content.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  const frontmatterMatch = normalized.match(/^---\n([\s\S]*?)\n---/);

  if (!frontmatterMatch) {
    return { name: null, description: null };
  }

  const frontmatter = frontmatterMatch[1];

  // Try yaml.load first with JSON schema (safest, no type coercion issues)
  try {
    const parsed = yaml.load(frontmatter, { schema: yaml.JSON_SCHEMA }) as Record<string, unknown> | null;

    // Check if yaml.load returned a valid object with the required fields
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      const name = typeof parsed.name === "string" && parsed.name.trim() ? parsed.name.trim() : null;
      const description = typeof parsed.description === "string" && parsed.description.trim()
        ? parsed.description.trim()
        : null;

      // Only return early if we found valid values
      if (name !== null || description !== null) {
        return { name, description };
      }
    }
  } catch (e) {
    // yaml.load failed, fall through to regex extraction
  }

  // Fallback: regex-based extraction for edge cases
  // (e.g., multi-line description values that yaml.load may mishandle)
  return extractFrontmatterByRegex(frontmatter);
};

/**
 * Fallback regex-based extraction when yaml.load fails.
 * Handles simple YAML key: value pairs including multi-line values and block scalars.
 */
const extractFrontmatterByRegex = (frontmatter: string): { name: string | null; description: string | null } => {
  let name: string | null = null;
  let description: string | null = null;

  // Extract name field - simple pattern: "name: value" at start of line
  const nameMatch = frontmatter.match(/^name:\s*(.+?)\s*$/m);
  if (nameMatch && nameMatch[1]) {
    name = nameMatch[1].trim();
  }

  // Extract description field - need to handle block scalars (">" and "|")
  // The key insight: "description:" line may be followed by ">" on the same line,
  // and then all indented lines are the value
  const descStartMatch = frontmatter.match(/^description:\s*/m);
  if (!descStartMatch) {
    return { name, description };
  }

  // Find the line number where description starts
  const lines = frontmatter.split('\n');
  let descLineIndex = -1;
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].match(/^description:\s*/)) {
      descLineIndex = i;
      break;
    }
  }

  if (descLineIndex === -1) {
    return { name, description };
  }

  const descStartLine = lines[descLineIndex];
  const remainingLines = lines.slice(descLineIndex + 1);

  // Check if description uses block scalar (">" or "|")
  const hasBlockScalar = /^(description:\s*)>|^(description:\s*)\|/.test(descStartLine);

  if (hasBlockScalar) {
    // Block scalar: collect all lines that have at least one leading space
    const contentLines: string[] = [];
    for (const line of remainingLines) {
      // Non-empty line without leading space ends the block
      if (line.length > 0 && !line.startsWith(' ') && !line.startsWith('\t')) {
        break;
      }
      // Collect the line, removing the leading space (YAML block scalars use 1 space indent)
      if (line.trim() !== '') {
        contentLines.push(line.replace(/^ /, ''));
      }
    }
    if (contentLines.length > 0) {
      description = contentLines.join('\n').trim();
    }
  } else {
    // Single-line value: capture everything after "description:"
    const inlineMatch = descStartLine.match(/^description:\s*(.+?)\s*$/);
    if (inlineMatch && inlineMatch[1]) {
      description = inlineMatch[1].trim();
    }
  }

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

  // Content may or may not have <SKILL> wrapper tags depending on source.
  // Try to extract the block content first.
  const skillBlockMatch = content.match(/<SKILL>([\s\S]*?)<\/SKILL>/i);
  const blockContent = skillBlockMatch ? skillBlockMatch[1] : content;

  // Normalize line endings so regex patterns work with CRLF (Windows) input
  const normalizedBlock = blockContent.replace(/\r\n/g, "\n").replace(/\r/g, "\n");

  // Try to match the frontmatter block. The content may have a leading newline
  // before the opening --- (e.g. "\n---\n..."), so we use indexOf-based approach
  // for more reliable matching than regex with non-greedy quantifiers.
  let frontmatter: string | null = null;
  let frontmatterStart = -1;
  let frontmatterEnd = -1;

  // Find opening --- (must be at start of line: position 0 or after \n)
  const firstDash = normalizedBlock.indexOf("---");
  if (firstDash !== -1) {
    const isAtLineStart = firstDash === 0 || normalizedBlock[firstDash - 1] === "\n";
    if (isAtLineStart) {
      frontmatterStart = firstDash;
      // Find closing --- (must be on its own line, after opening)
      const searchStart = frontmatterStart + 3;
      // First try "\n---" format
      let secondDash = normalizedBlock.indexOf("\n---", searchStart);
      if (secondDash !== -1) {
        frontmatterEnd = secondDash + 1; // Include the \n in the boundary
      } else {
        // Try to find "---" at line start
        let i = searchStart;
        while (i < normalizedBlock.length) {
          const nextDash = normalizedBlock.indexOf("---", i);
          if (nextDash === -1) break;
          const isClosingDash = nextDash === 0 || normalizedBlock[nextDash - 1] === "\n";
          if (isClosingDash) {
            frontmatterEnd = nextDash;
            break;
          }
          i = nextDash + 3;
        }
      }
      if (frontmatterEnd !== -1) {
        frontmatter = normalizedBlock.substring(frontmatterStart, frontmatterEnd + 3);
      }
    }
  }

  if (frontmatter) {
    // Extract YAML content between the opening --- and closing ---
    const yamlContent = frontmatter
      .replace(/^---/, "")
      .replace(/---$/, "")
      .trim();
    const parsed = yaml.load(yamlContent, { schema: yaml.JSON_SCHEMA }) as Record<string, unknown> | null;
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      result.name = typeof parsed.name === "string" ? parsed.name.trim() : "";
      result.description = typeof parsed.description === "string" ? parsed.description.trim() : "";
      result.tags = Array.isArray(parsed.tags) ? parsed.tags.filter((t): t is string => typeof t === "string") : [];
    }
    // Extract content after frontmatter (everything after the closing ---)
    result.contentWithoutFrontmatter = normalizedBlock.substring(frontmatterEnd + 3).trim();
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
