import assert from "node:assert/strict";
import test from "node:test";

import {
  consumeSkillCreationStream,
  createSkillFrontmatterStreamParser,
  isSafeSkillFilePath,
} from "../lib/skillCreationStream.ts";

const encoder = new TextEncoder();

function sseEvent(payload, newline = "\n") {
  return `data: ${JSON.stringify(payload)}${newline}${newline}`;
}

function streamFromBytes(bytes, chunkSizes = [bytes.length]) {
  return new ReadableStream({
    start(controller) {
      let offset = 0;
      let sizeIndex = 0;
      while (offset < bytes.length) {
        const requestedSize = chunkSizes[sizeIndex % chunkSizes.length];
        const end = Math.min(bytes.length, offset + requestedSize);
        controller.enqueue(bytes.slice(offset, end));
        offset = end;
        sizeIndex += 1;
      }
      controller.close();
    },
  });
}

function streamFromText(text, chunkSizes) {
  return streamFromBytes(encoder.encode(text), chunkSizes);
}

function createRecorder(overrides = {}) {
  const record = {
    thinkingVisible: [],
    steps: [],
    frontmatter: [],
    body: [],
    files: [],
    summaries: [],
    done: [],
    errors: [],
  };
  return {
    record,
    callbacks: {
      onStepCount: (step) => record.steps.push(step),
      onThinkingVisible: (visible) => record.thinkingVisible.push(visible),
      onThinkingUpdate: () => {},
      onFrontmatter: (content) => record.frontmatter.push(content),
      onSkillBody: (content) => record.body.push(content),
      onFileContent: (path, content, isNewFile) =>
        record.files.push({ path, content, isNewFile }),
      onSummary: (content) => record.summaries.push(content),
      onDone: (result) => record.done.push(result),
      onError: (message) => record.errors.push(message),
      ...overrides,
    },
  };
}

test("frontmatter parser waits for a split closing-delimiter newline", () => {
  const parser = createSkillFrontmatterStreamParser();

  assert.deepEqual(parser.update("---\nname: demo\ndescription: test\n---"), {
    body: "",
  });
  assert.deepEqual(parser.update("\n# Body"), {
    frontmatter: "name: demo\ndescription: test",
    body: "# Body",
  });
  assert.deepEqual(parser.finish(), { body: "" });
});

test("frontmatter parser accepts a closing delimiter at EOF", () => {
  const parser = createSkillFrontmatterStreamParser();

  parser.update("---\nname: demo\ndescription: test\n---");
  assert.deepEqual(parser.finish(), {
    frontmatter: "name: demo\ndescription: test",
    body: "",
  });
});

test("frontmatter parser accepts wrapper whitespace before SKILL.md", () => {
  const parser = createSkillFrontmatterStreamParser();

  assert.deepEqual(parser.update("\n  --"), { body: "" });
  assert.deepEqual(
    parser.update("-\nname: wrapped\ndescription: Wrapped skill\n---\n# Body"),
    {
      frontmatter: "name: wrapped\ndescription: Wrapped skill",
      body: "# Body",
    }
  );
});

test("consumer reconstructs unicode, frontmatter, files, summary, and terminal state", async () => {
  const streamText = [
    ": connected\r\n\r\n",
    sseEvent({ type: "step_count", content: "Step 1" }, "\r\n"),
    sseEvent({
      type: "skill_body",
      content: "\n---\nname: report-writer\ndescription: 中文公文写作\n",
    }),
    sseEvent({ type: "skill_body", content: "tags:\n  - writing\n---" }),
    sseEvent({ type: "skill_body", content: "\n# 公文写作\n正文" }),
    sseEvent({
      type: "file_content",
      path: "references/template.md",
      content: "",
      is_new_file: true,
    }),
    sseEvent({
      type: "file_content",
      path: "references/template.md",
      content: "模板内容",
    }),
    sseEvent({ type: "summary", content: "创建完成" }),
    sseEvent({ type: "done" }),
  ].join("");
  const { callbacks, record } = createRecorder();

  const result = await consumeSkillCreationStream(
    streamFromText(streamText, [1, 2, 5, 3]),
    callbacks
  );

  assert.deepEqual(record.steps, [1]);
  assert.equal(
    record.frontmatter.at(-1),
    "name: report-writer\ndescription: 中文公文写作\ntags:\n  - writing"
  );
  assert.equal(record.body.join(""), "# 公文写作\n正文");
  assert.deepEqual(result.skillTabs, [
    {
      path: "SKILL.md",
      content:
        "\n---\nname: report-writer\ndescription: 中文公文写作\ntags:\n  - writing\n---\n# 公文写作\n正文",
    },
    { path: "references/template.md", content: "模板内容" },
  ]);
  assert.equal(result.summaryContent, "创建完成");
  assert.equal(record.done.length, 1);
  assert.deepEqual(record.errors, []);
  assert.deepEqual(record.thinkingVisible, [true, false, false]);
});

test("consumer handles a terminal frame without a trailing newline", async () => {
  const text =
    sseEvent({
      type: "skill_body",
      content: "---\nname: demo\ndescription: test\n---\n# Body",
    }) + `data: ${JSON.stringify({ type: "done" })}`;
  const { callbacks, record } = createRecorder();

  await consumeSkillCreationStream(streamFromText(text, [7]), callbacks);

  assert.equal(record.done.length, 1);
  assert.deepEqual(record.errors, []);
});

test("consumer reports premature EOF exactly once", async () => {
  const { callbacks, record } = createRecorder();

  await consumeSkillCreationStream(
    streamFromText(
      sseEvent({
        type: "skill_body",
        content: "---\nname: demo\ndescription: test\n---\n# Body",
      })
    ),
    callbacks
  );

  assert.deepEqual(record.errors, [
    "Skill stream ended before a terminal event was received",
  ]);
  assert.equal(record.done.length, 0);
});

test("consumer rejects done without content or complete frontmatter", async () => {
  const empty = createRecorder();
  await consumeSkillCreationStream(
    streamFromText(sseEvent({ type: "done" })),
    empty.callbacks
  );
  assert.deepEqual(empty.record.errors, [
    "Skill stream completed without SKILL.md content",
  ]);

  const missingFrontmatter = createRecorder();
  await consumeSkillCreationStream(
    streamFromText(
      sseEvent({ type: "skill_body", content: "# Body" }) +
        sseEvent({ type: "done" })
    ),
    missingFrontmatter.callbacks
  );
  assert.deepEqual(missingFrontmatter.record.errors, [
    "Skill stream completed without complete YAML frontmatter",
  ]);
});

test("consumer keeps the first error terminal and ignores later done", async () => {
  const { callbacks, record } = createRecorder();
  const text =
    sseEvent({ type: "error", message: "model failed" }) +
    sseEvent({ type: "done" });

  await consumeSkillCreationStream(streamFromText(text), callbacks);

  assert.deepEqual(record.errors, ["model failed"]);
  assert.equal(record.done.length, 0);
});

test("consumer ignores malformed frames but warns and continues", async () => {
  const warnings = [];
  const { callbacks, record } = createRecorder();
  const text =
    "data: {not-json}\n\n" +
    sseEvent({
      type: "skill_body",
      content: "---\nname: demo\ndescription: test\n---\n# Body",
    }) +
    sseEvent({ type: "done" });

  await consumeSkillCreationStream(streamFromText(text, [2, 1]), callbacks, {
    onProtocolWarning: (message) => warnings.push(message),
  });

  assert.deepEqual(warnings, ["Ignoring malformed skill stream event"]);
  assert.equal(record.done.length, 1);
});

test("consumer rejects unsafe generated file paths", async () => {
  const { callbacks, record } = createRecorder();
  const text =
    sseEvent({
      type: "skill_body",
      content: "---\nname: demo\ndescription: test\n---\n# Body",
    }) +
    sseEvent({
      type: "file_content",
      path: "../secret.txt",
      content: "secret",
    }) +
    sseEvent({ type: "done" });

  await consumeSkillCreationStream(streamFromText(text), callbacks);

  assert.deepEqual(record.errors, [
    "Skill stream returned an invalid file path: ../secret.txt",
  ]);
  assert.equal(record.done.length, 0);
});

test("consumer does not convert an intentional abort into an error", async () => {
  const abortController = new AbortController();
  abortController.abort();
  const { callbacks, record } = createRecorder();

  await consumeSkillCreationStream(streamFromText(""), callbacks, {
    signal: abortController.signal,
  });

  assert.deepEqual(record.errors, []);
  assert.equal(record.done.length, 0);
});

test("callback failures propagate instead of being mislabeled as malformed SSE", async () => {
  const expected = new Error("render failed");
  const { callbacks } = createRecorder({
    onSkillBody: () => {
      throw expected;
    },
  });
  const text =
    sseEvent({
      type: "skill_body",
      content: "---\nname: demo\ndescription: test\n---\n# Body",
    }) + sseEvent({ type: "done" });

  await assert.rejects(
    consumeSkillCreationStream(streamFromText(text), callbacks),
    expected
  );
});

test("file path validation accepts only normalized relative paths", () => {
  assert.equal(isSafeSkillFilePath("references/guide.md"), true);
  assert.equal(isSafeSkillFilePath("scripts/run.py"), true);
  assert.equal(isSafeSkillFilePath("/absolute.txt"), false);
  assert.equal(isSafeSkillFilePath("../secret.txt"), false);
  assert.equal(isSafeSkillFilePath("references//guide.md"), false);
  assert.equal(isSafeSkillFilePath("references\\guide.md"), false);
});
