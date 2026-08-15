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
  console.log('[A2UI_PARSER] extractTaggedBlocks found:', taggedBlocks.length, 'blocks');
  if (taggedBlocks.length > 0) {
    result.isA2UI = true;
    result.content = taggedBlocks.join('\n');
    // Parse each tagged block as JSONL (multiple JSON objects separated by whitespace)
    result.blocks = parseTaggedBlockAsMessages(taggedBlocks);
    console.log('[A2UI_PARSER] parsed blocks after splitJsonObjects:', result.blocks.length, 'blocks');
    for (let i = 0; i < result.blocks.length; i++) {
      console.log('[A2UI_PARSER] block', i, 'type:', result.blocks[i].type, 'hasParsed:', !!result.blocks[i].parsed);
    }

    // Extract schema from beginRendering or first object
    for (const block of result.blocks) {
      if (block.type === 'lifecycle' && block.parsed) {
        const msg = block.parsed as Record<string, unknown>;
        const payload = getMessagePayload(msg);
        const schema = payload.schema || payload.root;
        if (schema) {
          result.schema = schema as Record<string, unknown>;
          result.messageType = getMessageType(msg);
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

  // Try JSONL format (one JSON per line, or multiple JSON objects on one line)
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
        } else {
          // Single JSON parse failed - try splitting into multiple JSON objects
          // (handles concatenated JSON objects like {...}{...}{...} on one line)
          const subMessages = splitJsonObjects(trimmedLine);
          console.log('[A2UI_PARSER] JSONL fallback: splitJsonObjects found', subMessages.length, 'sub-messages on one line');
          for (const msgStr of subMessages) {
            const subParsed = safeParseJSON(msgStr);
            if (subParsed && isValidA2UIObject(subParsed)) {
              jsonLines.push(msgStr);
              result.blocks.push({
                type: classifyBlock(msgStr),
                content: msgStr,
                parsed: subParsed,
              });
            }
          }
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
 * Parse tagged block contents as JSONL (multiple JSON objects in one block).
 * Splits each block into individual A2UI messages and creates separate blocks.
 */
function parseTaggedBlockAsMessages(blockContents: string[]): A2UIBlock[] {
  const blocks: A2UIBlock[] = [];
  for (const content of blockContents) {
    console.log('[A2UI_PARSER] parseTaggedBlockAsMessages: content length:', content.length);
    const messages = splitJsonObjects(content);
    console.log('[A2UI_PARSER] splitJsonObjects returned:', messages.length, 'messages');
    if (messages.length === 0) {
      // Couldn't split - treat entire content as one block
      blocks.push({
        type: classifyBlock(content),
        content,
        parsed: safeParseJSON(content),
      });
    } else {
      for (const msgStr of messages) {
        blocks.push({
          type: classifyBlock(msgStr),
          content: msgStr,
          parsed: safeParseJSON(msgStr),
        });
      }
    }
  }
  return blocks;
}

/**
 * Split a string containing multiple JSON objects into individual JSON strings.
 * Uses progressive parse: for each '{' found, tries progressively longer substrings
 * until a valid JSON object is parsed. Falls back to brace-counting for speed.
 */
function splitJsonObjects(content: string): string[] {
  const result: string[] = [];
  let idx = 0;
  const len = content.length;

  while (idx < len) {
    // Skip whitespace
    while (idx < len && /\s/.test(content[idx])) {
      idx++;
    }
    if (idx >= len) break;
    if (content[idx] !== '{') {
      // Not a JSON object - try to find next '{'
      idx++;
      while (idx < len && content[idx] !== '{') {
        idx++;
      }
      continue;
    }

    const start = idx;

    // Fast path: brace-counting to find candidate end
    let braceCount = 0;
    let inString = false;
    let escapeNext = false;
    let candidateEnd = -1;
    let fastIdx = start;
    while (fastIdx < len) {
      const ch = content[fastIdx];
      if (escapeNext) {
        escapeNext = false;
        fastIdx++;
        continue;
      }
      if (ch === '\\' && inString) {
        escapeNext = true;
        fastIdx++;
        continue;
      }
      if (ch === '"') {
        inString = !inString;
      }
      if (!inString) {
        if (ch === '{') braceCount++;
        if (ch === '}') braceCount--;
        if (braceCount === 0) {
          candidateEnd = fastIdx + 1;
          break;
        }
      }
      fastIdx++;
    }

    if (candidateEnd > start) {
      const candidate = content.slice(start, candidateEnd);
      if (safeParseJSON(candidate)) {
        result.push(candidate);
        idx = candidateEnd;
        continue;
      }
      // Brace-counting found a boundary but JSON is invalid - try progressive parse
      console.warn('[A2UI_PARSER] splitJsonObjects: brace-counting found boundary but JSON parse failed at position', start, 'length:', candidate.length);
    }

    // Slow path: progressive parse - try increasingly longer substrings
    let found = false;
    // Start from a reasonable minimum (at least 2 chars for "{}")
    for (let end = start + 2; end <= len; end++) {
      const candidate = content.slice(start, end);
      try {
        const parsed = JSON.parse(candidate);
        if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
          result.push(candidate);
          idx = end;
          found = true;
          break;
        }
      } catch {
        // continue trying longer substrings
      }
    }

    if (!found) {
      console.warn('[A2UI_PARSER] splitJsonObjects: failed to parse JSON object at position', start, 'preview:', content.slice(start, Math.min(start + 100, len)));
      // Skip this '{' and try to find the next one
      idx++;
      while (idx < len && content[idx] !== '{') {
        idx++;
      }
    }
  }
  return result;
}

/**
 * A2UI message type keys (matching backend constants)
 */
const A2UI_MESSAGE_KEYS = new Set([
  'beginRendering',
  'surfaceUpdate',
  'dataModelUpdate',
  'deleteSurface',
]);

/**
 * Extract the message type key from an A2UI message object.
 * Handles both: {"beginRendering": {...}} and {"messageType": "beginRendering", ...}
 */
function getMessageType(obj: Record<string, unknown>): string | null {
  if (obj.messageType && typeof obj.messageType === 'string') {
    return obj.messageType;
  }
  for (const key of A2UI_MESSAGE_KEYS) {
    if (key in obj) return key;
  }
  return null;
}

/**
 * Extract the message payload from an A2UI message object.
 * For {"beginRendering": {...}}, returns the inner object.
 * For {"messageType": "beginRendering", ...}, returns the whole object.
 */
function getMessagePayload(obj: Record<string, unknown>): Record<string, unknown> {
  for (const key of A2UI_MESSAGE_KEYS) {
    if (key in obj && typeof obj[key] === 'object' && obj[key] !== null) {
      return obj[key] as Record<string, unknown>;
    }
  }
  return obj;
}

/**
 * Classify the type of an A2UI block
 */
function classifyBlock(content: string): 'schema' | 'batch' | 'lifecycle' {
  const parsed = safeParseJSON(content);
  if (!parsed) return 'batch';

  const obj = parsed as Record<string, unknown>;
  const msgType = getMessageType(obj);

  if (msgType === 'beginRendering' || msgType === 'endRendering') {
    return 'lifecycle';
  }
  if (msgType === 'surfaceUpdate' || msgType === 'dataModelUpdate' || msgType === 'deleteSurface') {
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
  if (getMessageType(obj)) {
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
  return content.includes(A2UI_OPEN_TAG)
    || /\{[\s\S]*?"type"[\s\S]*?"properties"/.test(content.slice(0, 500))
    || /\b(beginRendering|surfaceUpdate|dataModelUpdate)\b/.test(content.slice(0, 500));
}