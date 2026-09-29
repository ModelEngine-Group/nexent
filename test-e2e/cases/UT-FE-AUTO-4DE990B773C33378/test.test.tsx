import { test } from 'vitest';
import assert from 'node:assert/strict';
import * as fs from 'node:fs';
import * as path from 'node:path';

const REL_SOURCES = {
  page: path.join('frontend', 'app', '[locale]', 'newchat', 'page.tsx'),
  adapter: path.join('frontend', 'app', '[locale]', 'newchat', 'adapter', 'conversation-thread-list-adapter.tsx'),
  thread: path.join('frontend', 'app', '[locale]', 'newchat', 'assistant-ui', 'thread.tsx'),
};

function findRepoRoot(): string {
  const configured = process.env.NEXENT_REPO;
  if (configured && fs.existsSync(path.join(configured, REL_SOURCES.page))) {
    return configured;
  }
  let dir = process.cwd();
  for (let i = 0; i < 8; i += 1) {
    if (fs.existsSync(path.join(dir, REL_SOURCES.page))) {
      return dir;
    }
    const parent = path.dirname(dir);
    if (parent === dir) {
      break;
    }
    dir = parent;
  }
  throw new Error('unable to locate repository root containing newchat sources');
}

function readSource(relPath: string): string {
  return fs.readFileSync(path.join(findRepoRoot(), relPath), 'utf8');
}

function assertOrdered(src: string, markers: string[], label: string): void {
  let cursor = -1;
  for (const marker of markers) {
    const idx = src.indexOf(marker, cursor + 1);
    assert.ok(idx !== -1, label + ': expected to find ' + marker + ' in order');
    cursor = idx;
  }
}

test('UT-FE-AUTO-4DE990B773C33378 landing agent selection restores agent and binds agentId via initialize + updateCustom', () => {
  const src = readSource(REL_SOURCES.page);
  const start = src.indexOf('handleAgentSelectedFromLanding');
  assert.ok(start !== -1, 'handleAgentSelectedFromLanding should exist in page.tsx');
  const end = src.indexOf('onAgentSelected(agent);', start);
  assert.ok(end !== -1, 'onAgentSelected(agent) should follow handleAgentSelectedFromLanding');
  const block = src.slice(start, end + 'onAgentSelected(agent);'.length);
  assertOrdered(
    block,
    [
      'shouldRestoreAgentRef.current = true',
      'runtime.threads.switchToNewThread()',
      'runtime.threads.getItemById(',
      'mainThreadId',
      'thread.initialize()',
      'thread.updateCustom({ agentId: agent.id })',
    ],
    'handleAgentSelectedFromLanding',
  );
});

test('handleThreadBack clears restore flag then switches thread and returns to landing', () => {
  const src = readSource(REL_SOURCES.page);
  const start = src.indexOf('const handleThreadBack = useCallback');
  assert.ok(start !== -1, 'handleThreadBack should exist in page.tsx');
  const end = src.indexOf('[onBack, runtime]', start);
  assert.ok(end !== -1, 'handleThreadBack dependencies should exist');
  const block = src.slice(start, end);
  assertOrdered(
    block,
    [
      'shouldRestoreAgentRef.current = false',
      'runtime.threads.switchToNewThread()',
      'onBack()',
    ],
    'handleThreadBack',
  );
});

test('adapter updateCustom is a no-op with nullable custom metadata signature', () => {
  const src = readSource(REL_SOURCES.adapter);
  const start = src.indexOf('async updateCustom(');
  assert.ok(start !== -1, 'updateCustom should exist in conversation-thread-list-adapter.tsx');
  const end = src.indexOf('async rename(', start);
  assert.ok(end !== -1, 'rename should follow updateCustom');
  const block = src.slice(start, end);
  assert.ok(block.includes('_remoteId: string'), 'updateCustom should accept _remoteId');
  assert.ok(block.includes('_custom: Record<string, unknown> | undefined'), 'updateCustom should accept nullable custom metadata');
  assert.ok(block.includes('Promise<void>'), 'updateCustom returns nothing');
  assert.ok(block.includes('return;'), 'updateCustom body is a no-op');
  assert.ok(!block.includes('conversationService.create'), 'updateCustom must not create a backend conversation');
});

test('adapter initialize returns empty remoteId/externalId without backend creation', () => {
  const src = readSource(REL_SOURCES.adapter);
  const start = src.indexOf('async initialize(_threadId: string)');
  assert.ok(start !== -1, 'initialize should exist in conversation-thread-list-adapter.tsx');
  const end = src.indexOf('async updateCustom(', start);
  assert.ok(end !== -1, 'updateCustom should follow initialize');
  const block = src.slice(start, end);
  assert.ok(block.includes('remoteId: ""'), 'initialize should return empty remoteId');
  assert.ok(block.includes('externalId: ""'), 'initialize should return empty externalId');
  assert.ok(!/\bawait\s+conversationService\.create/.test(block), 'initialize must not create a backend conversation eagerly');
});

test('thread.tsx shows selected agent displayName under conversation title with messages and not embedded', () => {
  const src = readSource(REL_SOURCES.thread);
  const marker = src.indexOf('hasMessages && variant !== "embedded"');
  assert.ok(marker !== -1, 'embedded branch guard should exist in thread.tsx');
  const window = src.slice(marker, marker + 200);
  assert.ok(window.includes('{displayName}'), 'selected agent displayName should render under the title');
});
