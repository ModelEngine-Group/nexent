import {
  describe,
  it,
  expect,
  vi,
  beforeEach,
  afterEach,
  beforeAll,
} from 'vitest';
import {
  render,
  screen,
  fireEvent,
  waitFor,
  cleanup,
} from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import AidpCreateKbModal from '@/ext_components/aidp/components/AidpCreateKbModal';
import AidpUpdateKbModal from '@/ext_components/aidp/components/AidpUpdateKbModal';

const mocks = vi.hoisted(() => {
  const authUser: { role: string; tenantId: string | null } = {
    role: 'USER',
    tenantId: 'tenant-1',
  };
  return {
    authUser,
    listModels: vi.fn(),
    createKb: vi.fn(),
    uploadDocs: vi.fn(),
    setPermission: vi.fn(),
    partitionAidpFiles: vi.fn(),
    validateAidpFiles: vi.fn(),
  };
});

const antdMessage = vi.hoisted(() => ({
  error: vi.fn(),
  warning: vi.fn(),
  success: vi.fn(),
  info: vi.fn(),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'en' },
  }),
}));

vi.mock('@/components/providers/AuthorizationProvider', () => ({
  useAuthorizationContext: () => ({ user: mocks.authUser }),
}));

vi.mock('@/hooks/group/useGroupList', () => ({
  useGroupList: () => ({
    data: {
      groups: [
        { group_id: 1, group_name: 'Group A' },
        { group_id: 2, group_name: 'Group B' },
      ],
    },
    allGroupIds: [1, 2],
  }),
}));

vi.mock('@/ext_components/aidp/services/aidpKnowledgeService', () => ({
  default: {
    listModels: mocks.listModels,
    createKb: mocks.createKb,
    uploadDocs: mocks.uploadDocs,
    setPermission: mocks.setPermission,
  },
}));

vi.mock('@/services/uploadService', () => ({
  partitionAidpFiles: mocks.partitionAidpFiles,
  validateAidpFiles: mocks.validateAidpFiles,
}));

vi.mock('antd', async (importOriginal) => {
  const actual = await importOriginal();
  return { ...(actual as Record<string, unknown>), message: antdMessage };
});

const rafQueue: FrameRequestCallback[] = [];
const originalFetch = globalThis.fetch;

beforeAll(() => {
  (globalThis as unknown as Record<string, unknown>).requestAnimationFrame = (
    cb: FrameRequestCallback
  ) => {
    rafQueue.push(cb);
    return rafQueue.length;
  };
  (globalThis as unknown as Record<string, unknown>).cancelAnimationFrame =
    () => {};
  if (!(globalThis as unknown as Record<string, unknown>).matchMedia) {
    (globalThis as unknown as Record<string, unknown>).matchMedia = (
      query: string
    ) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    });
  }
  if (!(globalThis as unknown as Record<string, unknown>).ResizeObserver) {
    (globalThis as unknown as Record<string, unknown>).ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    };
  }
});

function flushRaf(): void {
  const cbs = rafQueue.splice(0);
  cbs.forEach((cb) => cb(0));
}

function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
}

interface CreateOverrides {
  open?: boolean;
  existingKbs?: any[];
  onCancel?: () => void;
  onSuccess?: (kb: any) => void;
}

function renderCreate(overrides: CreateOverrides = {}) {
  const onCancel = overrides.onCancel ?? vi.fn();
  const onSuccess = overrides.onSuccess ?? vi.fn();
  const qc = makeQueryClient();
  const utils = render(
    <QueryClientProvider client={qc}>
      <AidpCreateKbModal
        open={overrides.open ?? true}
        existingKbs={overrides.existingKbs ?? []}
        onCancel={onCancel}
        onSuccess={onSuccess}
      />
    </QueryClientProvider>
  );
  return { ...utils, onCancel, onSuccess, qc };
}

function renderUpdate(knowledgeBase: any, onSuccess?: (kb: any) => void) {
  const success = onSuccess ?? vi.fn();
  const onCancel = vi.fn();
  const qc = makeQueryClient();
  const utils = render(
    <QueryClientProvider client={qc}>
      <AidpUpdateKbModal
        open
        knowledgeBase={knowledgeBase}
        onCancel={onCancel}
        onSuccess={success}
      />
    </QueryClientProvider>
  );
  return { ...utils, onCancel, onSuccess: success, qc };
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.authUser.role = 'USER';
  mocks.authUser.tenantId = 'tenant-1';
  mocks.listModels.mockResolvedValue({
    service: 'llm',
    app: 'KnowledgeBase',
    models: [],
    total_count: 0,
  });
  mocks.createKb.mockResolvedValue({ kds_id: 'kb-1', kds_name: 'MyKB' });
  mocks.uploadDocs.mockResolvedValue({
    summary: { total: 0, success: 0, failed: 0 },
    success_list: [],
    failed_list: [],
  });
  mocks.setPermission.mockResolvedValue({
    success: true,
    permissions_saved: true,
    metadata_status: 'updated',
    metadata: { kds_id: 'kb-1', kds_name: 'MyKB' },
  });
  mocks.partitionAidpFiles.mockReturnValue({
    valid: [],
    invalidType: [],
    oversized: [],
    exceededCount: [],
  });
  mocks.validateAidpFiles.mockReturnValue({
    valid: [],
    invalidType: [],
    oversized: [],
    exceededCount: [],
  });
});

afterEach(() => {
  cleanup();
  rafQueue.length = 0;
  globalThis.fetch = originalFetch;
});

describe('AidpCreateKbModal', () => {
  it('UT-FE-AUTO-BA4BBC902BC06BE6 USER role hides permission config and submits PRIVATE with empty group_ids', async () => {
    mocks.authUser.role = 'USER';
    renderCreate({ existingKbs: [] });

    expect(screen.queryByText('aidpKnowledge.createIngroupPermission')).toBeNull();

    const nameInput = await screen.findByPlaceholderText(
      'aidpKnowledge.kbNamePlaceholder'
    );
    fireEvent.change(nameInput, { target: { value: 'MyKB' } });
    fireEvent.click(screen.getByText('aidpKnowledge.createNext'));

    const skipBtn = await screen.findByText(
      'aidpKnowledge.createSkipUpload'
    );
    fireEvent.click(skipBtn);

    await waitFor(() => expect(mocks.createKb).toHaveBeenCalledTimes(1));
    const payload = mocks.createKb.mock.calls[0][0];
    expect(payload.name).toBe('MyKB');
    expect(payload.ingroup_permission).toBe('PRIVATE');
    expect(payload.group_ids).toEqual([]);
    expect(payload.chunk_token_num).toBe(1024);
    expect(payload.chunk_overlap_num).toBe(128);
    expect(payload.caption_enable).toBe(0);
    expect(payload.vlm_model).toBe('');
  });

  it('non-USER role shows permission config and requires group_ids for READ_ONLY', async () => {
    mocks.authUser.role = 'SU';
    mocks.authUser.tenantId = 'tenant-1';
    renderCreate({ existingKbs: [] });

    expect(
      await screen.findByText('aidpKnowledge.createIngroupPermission')
    ).toBeTruthy();

    const nameInput = await screen.findByPlaceholderText(
      'aidpKnowledge.kbNamePlaceholder'
    );
    fireEvent.change(nameInput, { target: { value: 'MyKB' } });
    fireEvent.click(screen.getByText('aidpKnowledge.createNext'));

    await waitFor(() => {
      expect(screen.getByText('aidpKnowledge.createNext')).toBeTruthy();
    });
    expect(mocks.createKb).not.toHaveBeenCalled();
    expect(screen.queryByText('aidpKnowledge.createSkipUpload')).toBeNull();
  });

  it('duplicate name triggers createDuplicateName and stays on Step 0', async () => {
    mocks.authUser.role = 'USER';
    renderCreate({
      existingKbs: [{ kds_id: '1', kds_name: 'MyKB' }],
    });

    const nameInput = await screen.findByPlaceholderText(
      'aidpKnowledge.kbNamePlaceholder'
    );
    fireEvent.change(nameInput, { target: { value: 'MyKB' } });
    fireEvent.click(screen.getByText('aidpKnowledge.createNext'));

    await waitFor(() =>
      expect(antdMessage.error).toHaveBeenCalledWith(
        'aidpKnowledge.createDuplicateName'
      )
    );
    expect(screen.getByText('aidpKnowledge.createNext')).toBeTruthy();
    expect(mocks.createKb).not.toHaveBeenCalled();
  });

  it('back restores formValues into Step 0', async () => {
    mocks.authUser.role = 'USER';
    renderCreate({});

    const nameInput = await screen.findByPlaceholderText(
      'aidpKnowledge.kbNamePlaceholder'
    );
    fireEvent.change(nameInput, { target: { value: 'MyKB' } });
    fireEvent.click(screen.getByText('aidpKnowledge.createNext'));
    await screen.findByText('aidpKnowledge.createSkipUpload');

    fireEvent.click(screen.getByText('aidpKnowledge.createBack'));

    const restored = await screen.findByPlaceholderText(
      'aidpKnowledge.kbNamePlaceholder'
    );
    expect((restored as HTMLInputElement).value).toBe('MyKB');
  });

  it('caption disabled hides vlm_model picker and submits empty vlm_model', async () => {
    mocks.authUser.role = 'USER';
    mocks.listModels.mockResolvedValue({
      service: 'llm',
      app: 'KnowledgeBase',
      models: [{ model_name: 'Qwen3-VL-8B-Instruct' }],
      total_count: 1,
    });
    renderCreate({});

    await screen.findByPlaceholderText('aidpKnowledge.kbNamePlaceholder');
    await waitFor(() => expect(mocks.listModels).toHaveBeenCalled());
    expect(screen.queryByText('aidpKnowledge.createVlmModel')).toBeNull();

    const nameInput = screen.getByPlaceholderText(
      'aidpKnowledge.kbNamePlaceholder'
    );
    fireEvent.change(nameInput, { target: { value: 'MyKB' } });
    fireEvent.click(screen.getByText('aidpKnowledge.createNext'));
    fireEvent.click(
      await screen.findByText('aidpKnowledge.createSkipUpload')
    );

    await waitFor(() => expect(mocks.createKb).toHaveBeenCalledTimes(1));
    expect(mocks.createKb.mock.calls[0][0].vlm_model).toBe('');
  });

  async function submitWithCaption(models: any[]): Promise<any> {
    mocks.listModels.mockResolvedValue({
      service: 'llm',
      app: 'KnowledgeBase',
      models,
      total_count: models.length,
    });
    renderCreate({});
    await waitFor(() => expect(mocks.listModels).toHaveBeenCalled());

    const switchEl = await screen.findByRole('switch');
    fireEvent.click(switchEl);
    await screen.findByText('aidpKnowledge.createVlmModel');

    const nameInput = screen.getByPlaceholderText(
      'aidpKnowledge.kbNamePlaceholder'
    );
    fireEvent.change(nameInput, { target: { value: 'MyKB' } });
    fireEvent.click(screen.getByText('aidpKnowledge.createNext'));
    fireEvent.click(
      await screen.findByText('aidpKnowledge.createSkipUpload')
    );
    await waitFor(() => expect(mocks.createKb).toHaveBeenCalledTimes(1));
    return mocks.createKb.mock.calls[0][0];
  }

  it('caption enabled prefers Qwen3-VL-8B-Instruct when present', async () => {
    mocks.authUser.role = 'USER';
    const payload = await submitWithCaption([
      { model_name: 'Model-A' },
      { model_name: 'Qwen3-VL-8B-Instruct' },
    ]);
    expect(payload.vlm_model).toBe('Qwen3-VL-8B-Instruct');
  });

  it('caption enabled falls back to first model when preferred absent', async () => {
    mocks.authUser.role = 'USER';
    const payload = await submitWithCaption([
      { model_name: 'Model-A' },
      { model_name: 'Model-B' },
    ]);
    expect(payload.vlm_model).toBe('Model-A');
  });

  it('caption enabled falls back to Qwen3-VL-8B-Instruct on empty list', async () => {
    mocks.authUser.role = 'USER';
    const payload = await submitWithCaption([]);
    expect(payload.vlm_model).toBe('Qwen3-VL-8B-Instruct');
  });

  it('beforeUpload partitions once per multi-select batch and only adds valid files', async () => {
    mocks.authUser.role = 'USER';
    const fileA = new File(['a'], 'a.txt', { type: 'text/plain' });
    const fileB = new File(['b'], 'b.exe', {
      type: 'application/octet-stream',
    });
    mocks.partitionAidpFiles.mockReturnValue({
      valid: [fileA],
      invalidType: [fileB],
      oversized: [],
      exceededCount: [],
    });

    const { container } = renderCreate({});
    const nameInput = await screen.findByPlaceholderText(
      'aidpKnowledge.kbNamePlaceholder'
    );
    fireEvent.change(nameInput, { target: { value: 'MyKB' } });
    fireEvent.click(screen.getByText('aidpKnowledge.createNext'));
    await screen.findByText('aidpKnowledge.createSkipUpload');

    const fileInput = document.querySelector(
      'input[type=file]'
    ) as HTMLInputElement;
    fireEvent.change(fileInput, { target: { files: [fileA, fileB] } });
    flushRaf();

    await waitFor(() =>
      expect(mocks.partitionAidpFiles).toHaveBeenCalledTimes(1)
    );
    await screen.findByText('a.txt');
    expect(screen.queryByText('b.exe')).toBeNull();
  });

  it('skip upload does not re-validate files', async () => {
    mocks.authUser.role = 'USER';
    const fileA = new File(['a'], 'a.txt', { type: 'text/plain' });
    mocks.partitionAidpFiles.mockReturnValue({
      valid: [fileA],
      invalidType: [],
      oversized: [],
      exceededCount: [],
    });

    const { container } = renderCreate({});
    const nameInput = await screen.findByPlaceholderText(
      'aidpKnowledge.kbNamePlaceholder'
    );
    fireEvent.change(nameInput, { target: { value: 'MyKB' } });
    fireEvent.click(screen.getByText('aidpKnowledge.createNext'));
    await screen.findByText('aidpKnowledge.createSkipUpload');

    const fileInput = document.querySelector(
      'input[type=file]'
    ) as HTMLInputElement;
    fireEvent.change(fileInput, { target: { files: [fileA] } });
    flushRaf();
    await screen.findByText('a.txt');

    fireEvent.click(screen.getByText('aidpKnowledge.createSkipUpload'));
    await waitFor(() => expect(mocks.createKb).toHaveBeenCalledTimes(1));
    expect(mocks.validateAidpFiles).not.toHaveBeenCalled();
    expect(mocks.uploadDocs).not.toHaveBeenCalled();
  });

  it('submit re-validates files as defense-in-depth before create/upload', async () => {
    mocks.authUser.role = 'USER';
    const fileA = new File(['a'], 'a.txt', { type: 'text/plain' });
    mocks.partitionAidpFiles.mockReturnValue({
      valid: [fileA],
      invalidType: [],
      oversized: [],
      exceededCount: [],
    });
    mocks.validateAidpFiles.mockReturnValue({
      valid: [fileA],
      invalidType: [],
      oversized: [],
      exceededCount: [],
    });

    const { container } = renderCreate({});
    const nameInput = await screen.findByPlaceholderText(
      'aidpKnowledge.kbNamePlaceholder'
    );
    fireEvent.change(nameInput, { target: { value: 'MyKB' } });
    fireEvent.click(screen.getByText('aidpKnowledge.createNext'));
    await screen.findByText('aidpKnowledge.createSkipUpload');

    const fileInput = document.querySelector(
      'input[type=file]'
    ) as HTMLInputElement;
    fireEvent.change(fileInput, { target: { files: [fileA] } });
    flushRaf();
    await screen.findByText('a.txt');

    fireEvent.click(screen.getByText('aidpKnowledge.createSubmit'));
    await waitFor(() => expect(mocks.createKb).toHaveBeenCalledTimes(1));
    expect(mocks.validateAidpFiles).toHaveBeenCalledTimes(1);
    expect(mocks.uploadDocs).toHaveBeenCalledTimes(1);
  });
});

describe('AidpUpdateKbModal', () => {
  it('no changes calls onSuccess with original and skips setPermission', async () => {
    mocks.authUser.role = 'USER';
    const kb = {
      kds_id: 'kb-1',
      kds_name: 'MyKB',
      description: 'desc',
      ingroup_permission: 'PRIVATE',
      group_ids: [],
    };
    const onSuccess = vi.fn();
    renderUpdate(kb, onSuccess);

    await screen.findByPlaceholderText('aidpKnowledge.kbNamePlaceholder');
    fireEvent.click(screen.getByText('common.confirm'));

    await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));
    expect(onSuccess).toHaveBeenCalledWith(kb);
    expect(mocks.setPermission).not.toHaveBeenCalled();
  });

  it('changed name sends only changed field to setPermission', async () => {
    mocks.authUser.role = 'USER';
    const kb = {
      kds_id: 'kb-1',
      kds_name: 'MyKB',
      description: 'desc',
      ingroup_permission: 'PRIVATE',
      group_ids: [],
    };
    const onSuccess = vi.fn();
    renderUpdate(kb, onSuccess);

    const nameInput = await screen.findByPlaceholderText(
      'aidpKnowledge.kbNamePlaceholder'
    );
    fireEvent.change(nameInput, { target: { value: 'NewName' } });
    fireEvent.click(screen.getByText('common.confirm'));

    await waitFor(() => expect(mocks.setPermission).toHaveBeenCalledTimes(1));
    const [id, payload] = mocks.setPermission.mock.calls[0];
    expect(id).toBe('kb-1');
    expect(payload.name).toBe('NewName');
    expect(payload).not.toHaveProperty('description');
    expect(payload.ingroup_permission).toBe('PRIVATE');
    expect(payload.group_ids).toEqual([]);
  });

  it('metadata failed warns and rolls back name/description', async () => {
    mocks.authUser.role = 'USER';
    mocks.setPermission.mockResolvedValue({
      success: true,
      permissions_saved: true,
      metadata_status: 'failed',
      metadata: { kds_id: 'kb-1', kds_name: 'NewName' },
    });
    const kb = {
      kds_id: 'kb-1',
      kds_name: 'MyKB',
      description: 'desc',
      ingroup_permission: 'PRIVATE',
      group_ids: [],
    };
    const onSuccess = vi.fn();
    renderUpdate(kb, onSuccess);

    const nameInput = await screen.findByPlaceholderText(
      'aidpKnowledge.kbNamePlaceholder'
    );
    fireEvent.change(nameInput, { target: { value: 'NewName' } });
    fireEvent.click(screen.getByText('common.confirm'));

    await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));
    expect(antdMessage.warning).toHaveBeenCalledWith(
      'aidpKnowledge.updateKbMetadataFailed'
    );
    const result = onSuccess.mock.calls[0][0];
    expect(result.kds_name).toBe('MyKB');
    expect(result.description).toBe('desc');
  });
});

describe('aidpKnowledgeService.uploadDocs', () => {
  async function loadRealService(): Promise<any> {
    const mod = await vi.importActual(
      '@/ext_components/aidp/services/aidpKnowledgeService'
    );
    return mod.default;
  }

  function stubFetchError(body: string, status = 500): void {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status,
      statusText: 'Internal Server Error',
      text: async () => body,
      json: async () => JSON.parse(body),
    }) as unknown as typeof fetch;
  }

  it('builds multipart FormData and strips Content-Type', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        summary: { total: 2, success: 2, failed: 0 },
        success_list: [],
        failed_list: [],
      }),
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const realService = await loadRealService();
    const f1 = new File(['x'], 'a.txt', { type: 'text/plain' });
    const f2 = new File(['y'], 'b.txt', { type: 'text/plain' });
    const result = await realService.uploadDocs('kb-1', [f1, f2]);

    expect(result.summary.total).toBe(2);
    const options = fetchMock.mock.calls[0][1];
    expect(options.body).toBeInstanceOf(FormData);
    const fd = options.body as FormData;
    expect(fd.getAll('files')).toHaveLength(2);
    expect(fd.getAll('files')[0]).toBe(f1);
    expect(fd.getAll('files')[1]).toBe(f2);
    expect(options.headers).not.toHaveProperty('Content-Type');
    expect(options.headers).not.toHaveProperty('Authorization');
    expect(options.headers).not.toHaveProperty('api_key');
  });

  it('maps details.upstream_reason first', async () => {
    stubFetchError(
      JSON.stringify({
        message: 'outer message',
        details: { upstream_reason: 'upstream boom' },
      })
    );
    const realService = await loadRealService();
    const f1 = new File(['x'], 'a.txt', { type: 'text/plain' });
    await expect(realService.uploadDocs('kb-1', [f1])).rejects.toThrow(
      'upstream boom'
    );
  });

  it('maps message when upstream_reason is absent', async () => {
    stubFetchError(JSON.stringify({ message: 'just a message' }));
    const realService = await loadRealService();
    const f1 = new File(['x'], 'a.txt', { type: 'text/plain' });
    await expect(realService.uploadDocs('kb-1', [f1])).rejects.toThrow(
      'just a message'
    );
  });

  it('falls back to raw text for non-JSON errors', async () => {
    stubFetchError('plain text failure');
    const realService = await loadRealService();
    const f1 = new File(['x'], 'a.txt', { type: 'text/plain' });
    await expect(realService.uploadDocs('kb-1', [f1])).rejects.toThrow(
      'plain text failure'
    );
  });
});
