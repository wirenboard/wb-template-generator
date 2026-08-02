import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// Тестируем НАСТОЯЩИЙ api.ts (глобальный setup мокает '../api' — обходим через importActual).
// Регресс: в серверном режиме fetchModels слал пустой multipart/form-data, и FastAPI
// отвечал 400 «There was an error parsing the body». Тело должно уходить только когда
// заданы свой URL/ключ; иначе POST без тела.

let realFetchModels: (config?: { apiUrl?: string; apiKey?: string }) => Promise<string[]>;

beforeEach(async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api');
  realFetchModels = actual.fetchModels;
});

afterEach(() => {
  vi.restoreAllMocks();
});

function mockOkFetch() {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ models: ['gpt-4o', 'gpt-4o-mini'] }),
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

describe('fetchModels', () => {
  it('серверный режим (без config) — POST без тела, не пустой multipart', async () => {
    const fetchMock = mockOkFetch();
    const models = await realFetchModels();
    expect(models).toEqual(['gpt-4o', 'gpt-4o-mini']);
    const [, init] = fetchMock.mock.calls[0];
    expect(init.method).toBe('POST');
    expect(init.body).toBeUndefined();
  });

  it('пустой config — тоже без тела', async () => {
    const fetchMock = mockOkFetch();
    await realFetchModels({});
    const [, init] = fetchMock.mock.calls[0];
    expect(init.body).toBeUndefined();
  });

  it('кастомный LLM (apiUrl задан) — тело FormData с полями', async () => {
    const fetchMock = mockOkFetch();
    await realFetchModels({ apiUrl: 'https://api.example.com/v1', apiKey: 'sk-x' });
    const [, init] = fetchMock.mock.calls[0];
    expect(init.body).toBeInstanceOf(FormData);
    expect(init.body.get('llm_api_url')).toBe('https://api.example.com/v1');
    expect(init.body.get('llm_api_key')).toBe('sk-x');
  });
});
