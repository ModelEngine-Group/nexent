/**
 * Pure helpers for consuming the NL2Skill SSE protocol.
 *
 * This module intentionally has no React or application-service dependencies so
 * stream framing and state transitions can be tested independently.
 */

export const SKILL_STREAM_TYPES = {
  STEP_COUNT: "step_count",
  THINKING: "thinking",
  FRONTMATTER: "frontmatter",
  SKILL_BODY: "skill_body",
  FILE_CONTENT: "file_content",
  SUMMARY: "summary",
  DONE: "done",
  ERROR: "error",
} as const;

export type StreamEventType =
  (typeof SKILL_STREAM_TYPES)[keyof typeof SKILL_STREAM_TYPES];

export interface SkillStreamEvent {
  type: StreamEventType | string;
  content?: string;
  path?: string;
  is_new_file?: boolean;
  message?: string;
}

export interface SkillStreamResult {
  skillTabs: { path: string; content: string }[];
  summaryContent: string;
}

export interface SkillStreamCallbacks {
  onTaskId?: (taskId: string) => void;
  onStepCount: (step: number, description: string) => void;
  onThinkingVisible: (visible: boolean) => void;
  onThinkingUpdate: (step: number, description: string) => void;
  onFrontmatter: (content: string) => void;
  onSkillBody: (content: string) => void;
  onFileContent: (path: string, content: string, isNewFile: boolean) => void;
  onSummary: (content: string) => void;
  onDone: (result: SkillStreamResult) => void;
  onError: (message: string) => void;
}

export interface ConsumeSkillStreamOptions {
  signal?: AbortSignal;
  onProtocolWarning?: (message: string, detail?: unknown) => void;
}

interface FrontmatterStreamUpdate {
  frontmatter?: string;
  body: string;
}

export function isSafeSkillFilePath(path: string): boolean {
  const normalized = path.trim();
  if (
    !normalized ||
    normalized.startsWith("/") ||
    normalized.includes("\\") ||
    normalized.includes("\0")
  ) {
    return false;
  }
  return normalized.split("/").every((part) => !["", ".", ".."].includes(part));
}

/**
 * Separate YAML frontmatter from a streamed SKILL.md body.
 *
 * A closing delimiter at the current buffer's end is kept pending until the
 * next chunk or EOF. This avoids leaking the delimiter's newline into the body
 * when `\n---` and the following `\n` arrive in separate network chunks.
 */
export function createSkillFrontmatterStreamParser(): {
  update: (chunk: string) => FrontmatterStreamUpdate;
  finish: () => FrontmatterStreamUpdate;
} {
  let state: "detecting" | "frontmatter" | "body" = "detecting";
  let buffer = "";
  let frontmatterStart = 0;
  const openingDelimiter = "---\n";

  const parseBufferedContent = (
    allowEofDelimiter: boolean
  ): FrontmatterStreamUpdate => {
    if (state === "body") {
      const body = buffer;
      buffer = "";
      return { body };
    }

    if (state === "detecting") {
      const candidate = buffer.trimStart();
      if (!candidate || openingDelimiter.startsWith(candidate)) {
        return { body: "" };
      }
      if (!candidate.startsWith(openingDelimiter)) {
        state = "body";
        const body = buffer;
        buffer = "";
        return { body };
      }
      frontmatterStart = buffer.length - candidate.length;
      state = "frontmatter";
    }

    const contentOffset = frontmatterStart + openingDelimiter.length;
    const content = buffer.slice(contentOffset);
    const closingMatch = (allowEofDelimiter ? /\n---(?:\n|$)/ : /\n---\n/).exec(
      content
    );
    if (!closingMatch) {
      return { body: "" };
    }

    const closingOffset = contentOffset + closingMatch.index;
    const bodyOffset = closingOffset + closingMatch[0].length;
    const frontmatter = buffer.slice(contentOffset, closingOffset);
    const body = buffer.slice(bodyOffset);
    buffer = "";
    state = "body";
    return { frontmatter, body };
  };

  return {
    update(chunk: string) {
      buffer += chunk;
      return parseBufferedContent(false);
    },
    finish() {
      const parsed = parseBufferedContent(true);
      if (parsed.frontmatter !== undefined || state === "body") {
        return parsed;
      }

      const body = buffer;
      buffer = "";
      state = "body";
      return { body };
    },
  };
}

export async function consumeSkillCreationStream(
  body: ReadableStream<Uint8Array>,
  callbacks: SkillStreamCallbacks,
  options: ConsumeSkillStreamOptions = {}
): Promise<SkillStreamResult> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  const frontmatterParser = createSkillFrontmatterStreamParser();
  const skillTabs: { path: string; content: string }[] = [
    { path: "SKILL.md", content: "" },
  ];

  let buffer = "";
  let terminalState: "pending" | "done" | "error" = "pending";
  let receivedSkillContent = false;
  let receivedCompleteFrontmatter = false;
  let explicitFrontmatter = "";
  let summaryContent = "";

  callbacks.onThinkingVisible(true);

  const failStream = (message: string) => {
    if (terminalState !== "pending") return;
    terminalState = "error";
    callbacks.onThinkingVisible(false);
    callbacks.onError(message);
  };

  const processEvent = (event: SkillStreamEvent) => {
    if (terminalState !== "pending") return;

    switch (event.type) {
      case SKILL_STREAM_TYPES.STEP_COUNT: {
        const stepMatch = String(event.content).match(/\d+/);
        const stepNum = stepMatch
          ? Number.parseInt(stepMatch[0], 10)
          : Number.NaN;
        if (!Number.isNaN(stepNum)) {
          callbacks.onThinkingUpdate(stepNum, "");
          callbacks.onStepCount(stepNum, "");
        }
        break;
      }

      case SKILL_STREAM_TYPES.THINKING:
        break;

      case SKILL_STREAM_TYPES.FRONTMATTER:
        if (event.content) {
          explicitFrontmatter += event.content;
          receivedCompleteFrontmatter = explicitFrontmatter.trim().length > 0;
          callbacks.onFrontmatter(explicitFrontmatter);
        }
        break;

      case SKILL_STREAM_TYPES.SKILL_BODY:
        if (event.content) {
          receivedSkillContent = true;
          skillTabs[0].content += event.content;
          const parsed = frontmatterParser.update(event.content);
          if (parsed.frontmatter !== undefined) {
            receivedCompleteFrontmatter = true;
            callbacks.onFrontmatter(parsed.frontmatter);
          }
          if (parsed.body) {
            callbacks.onSkillBody(parsed.body);
          }
        }
        break;

      case SKILL_STREAM_TYPES.FILE_CONTENT: {
        const filePath = String(event.path || "").trim();
        if (!isSafeSkillFilePath(filePath)) {
          failStream(
            `Skill stream returned an invalid file path: ${filePath || "<empty>"}`
          );
          break;
        }

        let fileTab = skillTabs.find((tab) => tab.path === filePath);
        if (!fileTab) {
          fileTab = { path: filePath, content: "" };
          skillTabs.push(fileTab);
        }
        if (event.content) {
          fileTab.content += event.content;
        }
        callbacks.onFileContent(
          filePath,
          event.content || "",
          !!event.is_new_file
        );
        break;
      }

      case SKILL_STREAM_TYPES.SUMMARY:
        if (event.content) {
          summaryContent += event.content;
          callbacks.onSummary(event.content);
        }
        break;

      case SKILL_STREAM_TYPES.DONE: {
        const trailing = frontmatterParser.finish();
        if (trailing.frontmatter !== undefined) {
          receivedCompleteFrontmatter = true;
          callbacks.onFrontmatter(trailing.frontmatter);
        }
        if (trailing.body) {
          callbacks.onSkillBody(trailing.body);
        }
        if (!receivedSkillContent) {
          failStream("Skill stream completed without SKILL.md content");
          break;
        }
        if (!receivedCompleteFrontmatter) {
          failStream(
            "Skill stream completed without complete YAML frontmatter"
          );
          break;
        }

        terminalState = "done";
        callbacks.onThinkingVisible(false);
        callbacks.onDone({ skillTabs, summaryContent });
        break;
      }

      case SKILL_STREAM_TYPES.ERROR:
        failStream(event.message || "Unknown error");
        break;

      default:
        options.onProtocolWarning?.(
          `Ignoring unknown skill stream event type: ${event.type}`,
          event
        );
    }
  };

  const processFrame = (frame: string) => {
    const dataLines = frame
      .split("\n")
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trimStart());
    if (dataLines.length === 0) return;

    const payload = dataLines.join("\n");
    let event: SkillStreamEvent;
    try {
      event = JSON.parse(payload) as SkillStreamEvent;
    } catch (error) {
      options.onProtocolWarning?.(
        "Ignoring malformed skill stream event",
        error
      );
      return;
    }
    processEvent(event);
  };

  const processBufferedFrames = (flush: boolean) => {
    const frames = buffer.split("\n\n");
    buffer = frames.pop() || "";
    for (const frame of frames) {
      processFrame(frame);
    }
    if (flush && buffer.trim()) {
      processFrame(buffer);
      buffer = "";
    }
  };

  try {
    while (true) {
      let readResult: ReadableStreamReadResult<Uint8Array>;
      try {
        readResult = await reader.read();
      } catch (readError: unknown) {
        if (
          options.signal?.aborted ||
          (readError instanceof Error &&
            (readError.name === "AbortError" ||
              readError.name === "AbortSignal"))
        ) {
          break;
        }
        throw readError;
      }

      if (readResult.done) break;
      buffer += decoder
        .decode(readResult.value, { stream: true })
        .replace(/\r/g, "");
      processBufferedFrames(false);
    }

    buffer += decoder.decode().replace(/\r/g, "");
    processBufferedFrames(true);
    if (terminalState === "pending" && !options.signal?.aborted) {
      failStream("Skill stream ended before a terminal event was received");
    }
  } finally {
    reader.releaseLock();
    callbacks.onThinkingVisible(false);
  }

  return { skillTabs, summaryContent };
}
