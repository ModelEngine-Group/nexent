/**
 * A2UI Message Parser
 *
 * Extracts structured A2UI JSON blocks from agent response content.
 * Supports multiple formats: tagged blocks, raw JSONL, and plain JSON.
 */

import { A2UI_BLOCK_PATTERN, A2UI_OPEN_TAG, A2UI_CLOSE_TAG, DEFAULT_A2UI_SCHEMA } from './constants';

export interface A2UIParseResult {
  isA2UI: boolean;
  schema: Record<string, unknown> | null;
  messageType: string | null;
  content: string;
  blocks: A2UIBlock[];
}

export interface A2UIBlock {
  type: 'schema' | 'batch' | 'lifecycle';
  content: string;
  parsed: Record<string, unknown> | null;
}

/**
 * Parse a message string and detect whether it contains A2UI content
 */
export function parseA2UIMessage(rawContent: string): A2UIParseResult {
  const result: A2UIParseResult = {
    isA2UI: false,
    schema: null,
    messageType: null,
    content: rawContent,
    blocks: [],
  };

  if (!rawContent || typeof rawContent !== 'string') {
    return result;
  }

  // Try tagged block format first
  const taggedBlocks = extractTaggedBlocks(rawContent);
  if (taggedBlocks.length > 0) {
    result.isA2UI = true;
    result.content = taggedBlocks.map((b) => b.content).join('\n');
    result.blocks = taggedBlocks.map((b) => ({
      type: classifyBlock(b.content),
      content: b.content,
      parsed: safeParseJSON(b.content),
    }));

    // Extract schema from beginRendering or first object
    for (const block of result.blocks) {
      if (block.type === 'lifecycle' && block.parsed) {
        const msg = block.parsed as Record<string, unknown>;
        if (msg.messageType === 'beginRendering' && msg.schema) {
          result.schema = msg.schema as Record<string, unknown>;
          result.messageType = msg.messageType as string;
          break;
        }
      }
      if (block.type === 'schema' && block.parsed) {
        result.schema = block.parsed;
      }
    }
    return result;
  }

  // Try raw JSON (whole message is a JSON object)
  const trimmed = rawContent.trim();
  if (trimmed.startsWith('{')) {
    const parsed = safeParseJSON(trimmed);
    if (parsed && isValidA2UIObject(parsed)) {
      result.isA2UI = true;
      result.schema = extractSchema(parsed);
      result.messageType = (parsed as Record<string, unknown>).messageType as string | null;
      result.blocks.push({
        type: classifyBlock(trimmed),
        content: trimmed,
        parsed,
      });
      return result;
    }
  }

  // Try JSONL format (one JSON per line)
  const lines = trimmed.split('\n');
  if (lines.length > 1) {
    const jsonLines: string[] = [];
    for (const line of lines) {
      const trimmedLine = line.trim();
      if (trimmedLine.startsWith('{')) {
        const parsed = safeParseJSON(trimmedLine);
        if (parsed && isValidA2UIObject(parsed)) {
          jsonLines.push(trimmedLine);
          result.blocks.push({
            type: classifyBlock(trimmedLine),
            content: trimmedLine,
            parsed,
          });
        }
      }
    }
    if (result.blocks.length > 0) {
      result.isA2UI = true;
      result.content = jsonLines.join('\n');
      // Extract schema
      for (const block of result.blocks) {
        if (block.parsed) {
          const msg = block.parsed as Record<string, unknown>;
          if (msg.messageType === 'beginRendering' && msg.schema) {
            result.schema = msg.schema as Record<string, unknown>;
            result.messageType = msg.messageType as string;
            break;
          }
        }
      }
      if (!result.schema && result.blocks.length > 0) {
        result.schema = result.blocks[0].parsed;
      }
    }
  }

  return result;
}

/**
 * Extract tagged A2UI blocks from content
 */
function extractTaggedBlocks(content: string): string[] {
  const blocks: string[] = [];
  const regex = new RegExp(
    `${escapeRegex(A2UI_OPEN_TAG)}([\\s\\S]*?)${escapeRegex(A2UI_CLOSE_TAG)}`,
    'g'
  );
  let match: RegExpExecArray | null;
  while ((match = regex.exec(content)) !== null) {
    if (match[1] && match[1].trim()) {
      blocks.push(match[1].trim());
    }
  }
  return blocks;
}

/**
 * Classify the type of an A2UI block
 */
function classifyBlock(content: string): 'schema' | 'batch' | 'lifecycle' {
  const parsed = safeParseJSON(content);
  if (!parsed) return 'batch';

  const obj = parsed as Record<string, unknown>;
  if (obj.messageType === 'beginRendering' || obj.messageType === 'endRendering') {
    return 'lifecycle';
  }
  if (obj.messageType === 'batch') {
    return 'batch';
  }
  if (obj.properties || obj.type) {
    return 'schema';
  }
  return 'batch';
}

/**
 * Check if an object looks like a valid A2UI object
 */
function isValidA2UIObject(obj: Record<string, unknown>): boolean {
  if (obj.messageType && typeof obj.messageType === 'string') {
    return true;
  }
  if (obj.version && obj.type) {
    return true;
  }
  if (obj.properties) {
    return true;
  }
  return false;
}

/**
 * Extract schema from an A2UI parsed object
 */
function extractSchema(obj: Record<string, unknown>): Record<string, unknown> | null {
  if (obj.schema && typeof obj.schema === 'object') {
    return obj.schema as Record<string, unknown>;
  }
  if (obj.properties && obj.type) {
    return obj;
  }
  return null;
}

/**
 * Safe JSON parse that returns null on failure
 */
function safeParseJSON(str: string): Record<string, unknown> | null {
  try {
    return JSON.parse(str) as Record<string, unknown>;
  } catch {
    return null;
  }
}

/**
 * Escape special regex characters
 */
function escapeRegex(str: string): string {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * Get the default schema when none is detected
 */
export function getDefaultSchema(): Record<string, unknown> {
  return { ...DEFAULT_A2UI_SCHEMA, properties: {} };
}

/**
 * Check if content might contain A2UI data (cheap check)
 */
export function mightContainA2UI(content: string): boolean {
  if (!content) return false;
  return content.includes(A2UI_OPEN_TAG) || /\{[\s\S]*?"type"[\s\S]*?"properties"/.test(content.slice(0, 500));
}