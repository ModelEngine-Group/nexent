import { describe, it, expect, vi, beforeEach } from 'vitest';
import { conversationService } from '@/services/conversationService';
import { remoteChatModelAdapter } from '@/app/[locale]/newchat/adapter/remote-chat-model-adapter';

vi.mock('@/services/conversationService', () => ({
  conversationService: {
    runAgent: vi.fn(),
    stop: vi.fn(),
  },
}));

const runAgentMock = conversationService.runAgent as unknown as ReturnType<
  typeof vi.fn
>;

function sseLine(type: string, content: string): string {
  return 'data: ' + JSON.stringify({ type: type, content: content });
}

function makeReader(lines: string[]): ReadableStreamDefaultReader<Uint8Array> {
  const encoder = new TextEncoder();
  const body = lines.map((line) => line + '\n').join('');
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(encoder.encode(body));
      controller.close();
    },
  });
  return stream.getReader();
}

interface HistorySummaryPayload {
  status?: string;
  summary?: { markdown?: string } | string;
  covered_through_message_id?: number;
}

function historySummaryChunk(payload: HistorySummaryPayload): string {
  return sseLine('history_summary', JSON.stringify(payload));
}

async function collect(lines: string[]): Promise<any[]> {
  runAgentMock.mockResolvedValue(makeReader(lines));
  const results: any[] = [];
  const stream = (remoteChatModelAdapter as unknown as {
    run: (options: unknown) => AsyncIterable<{ content: any[] }>;
  }).run({
    messages: [
      { id: 'm1', role: 'user', content: [{ type: 'text', text: 'hello' }] },
    ],
    context: {},
    runConfig: {},
  });
  for await (const result of stream) {
    results.push(result);
  }
  return results;
}

function historyParts(result: { content: any[] }): any[] {
  return (result.content ?? []).filter((part: any) => {
    return part?.type === 'data' && part?.name === 'history-summary';
  });
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('history_summary SSE 事件映射为 name=history-summary data part', () => {
  it('UT-FE-AUTO-9AD31E451F5DE0D1 compacting：生成 data part，status=compacting，不含 summary 正文', async () => {
    const results = await collect([historySummaryChunk({ status: 'compacting' })]);
    expect(results.length).toBe(2);
    const parts = historyParts(results[results.length - 1]);
    expect(parts).toHaveLength(1);
    expect(parts[0].data.status).toBe('compacting');
    expect(parts[0].data.summary).toBeUndefined();
  });

  it('accepted：data part 携带 summary.markdown 与 covered_through_message_id', async () => {
    const results = await collect([
      historySummaryChunk({
        status: 'accepted',
        summary: { markdown: '# 历史摘要' },
        covered_through_message_id: 12,
      }),
    ]);
    expect(results.length).toBe(2);
    const parts = historyParts(results[results.length - 1]);
    expect(parts).toHaveLength(1);
    expect(parts[0].data.status).toBe('accepted');
    expect(parts[0].data.summary.markdown).toBe('# 历史摘要');
    expect(parts[0].data.covered_through_message_id).toBe(12);
  });

  it('compacting 后 accepted：覆盖同一 part，始终只有一个 history-summary part', async () => {
    const results = await collect([
      historySummaryChunk({ status: 'compacting' }),
      historySummaryChunk({
        status: 'accepted',
        summary: { markdown: 'done' },
        covered_through_message_id: 3,
      }),
    ]);
    expect(results.length).toBe(3);
    expect(historyParts(results[0])).toHaveLength(1);
    expect(historyParts(results[0])[0].data.status).toBe('compacting');
    expect(historyParts(results[1])).toHaveLength(1);
    expect(historyParts(results[1])[0].data.status).toBe('accepted');
    expect(historyParts(results[2])).toHaveLength(1);
    expect(historyParts(results[2])[0].data.status).toBe('accepted');
  });

  it('accepted 后 idle：splice 移除已有 history-summary part', async () => {
    const results = await collect([
      historySummaryChunk({ status: 'accepted', summary: { markdown: 'x' } }),
      historySummaryChunk({ status: 'idle' }),
    ]);
    expect(results.length).toBe(3);
    expect(historyParts(results[0])).toHaveLength(1);
    expect(historyParts(results[1])).toHaveLength(0);
    expect(historyParts(results[2])).toHaveLength(0);
  });

  it('idle 且无已有 part：返回 true 但不产生卡片', async () => {
    const results = await collect([historySummaryChunk({ status: 'idle' })]);
    expect(results.length).toBe(2);
    expect(historyParts(results[results.length - 1])).toHaveLength(0);
  });

  it('malformed JSON：JSON.parse 失败后静默降级，不抛异常、不产生伪卡片', async () => {
    const results = await collect([sseLine('history_summary', 'not-valid-json{')]);
    expect(results.length).toBe(1);
    expect(historyParts(results[0])).toHaveLength(0);
  });

  it('未知 status：不改变渲染且不抛异常', async () => {
    const results = await collect([historySummaryChunk({ status: 'unknown' })]);
    expect(results.length).toBe(1);
    expect(historyParts(results[0])).toHaveLength(0);
  });

  it('输出不包含明文密钥', async () => {
    const results = await collect([
      historySummaryChunk({
        status: 'accepted',
        summary: { markdown: 'x' },
        covered_through_message_id: 1,
      }),
    ]);
    const serialized = JSON.stringify(results).toLowerCase();
    expect(serialized).not.toMatch(/api[-_]?key|access[-_]?token|password|secret/i);
  });
});
