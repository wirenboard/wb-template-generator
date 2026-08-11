import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// Тестируем НАСТОЯЩИЙ api.ts (глобальный setup мокает '../api' — обходим через importActual).
// Настройки своего LLM обязаны доходить до маршрута и обязаны идти в теле —
// в строке запроса ключ попадает в access-логи nginx.

let api: typeof import('../api');

const LLM_CONFIG = {
  apiUrl: 'https://user.example/v1',
  apiKey: 'sk-user',
  model: 'local-model',
  temperature: 0,
  timeout: 42,
  legacyMaxTokens: true,
};

const REGISTERS = [{ id: 'r0', address: 70000, name: 'Bad' }] as never;

beforeEach(async () => {
  api = await vi.importActual<typeof import('../api')>('../api');
});

afterEach(() => {
  vi.restoreAllMocks();
});

function stubSse() {
  // Пустой поток: интересен сам запрос, а не разбор событий
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    body: { getReader: () => ({ read: async () => ({ done: true, value: undefined }) }) },
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function callbacks() {
  return {
    onProgress: vi.fn(),
    onResult: vi.fn(),
    onError: vi.fn(),
    onDone: vi.fn(),
  };
}

describe('fixRegisters передаёт настройки своего LLM', () => {
  it('поля уходят в теле запроса в snake_case', async () => {
    const fetchMock = stubSse();

    await api.fixRegisters(REGISTERS, callbacks(), LLM_CONFIG);

    const [url, init] = fetchMock.mock.calls[0];
    const body = JSON.parse(init.body);
    expect(url).toBe('/api/fix-registers');
    expect(body.llm_api_url).toBe('https://user.example/v1');
    expect(body.llm_api_key).toBe('sk-user');
    expect(body.llm_model).toBe('local-model');
    expect(body.llm_timeout).toBe(42);
    expect(body.llm_legacy_max_tokens).toBe(true);
  });

  it('температура 0 доходит, а не теряется как falsy', async () => {
    const fetchMock = stubSse();

    await api.fixRegisters(REGISTERS, callbacks(), LLM_CONFIG);

    expect(JSON.parse(fetchMock.mock.calls[0][1].body).llm_temperature).toBe(0);
  });

  it('ключ не попадает в строку запроса — она уходит в access-логи', async () => {
    const fetchMock = stubSse();

    await api.fixRegisters(REGISTERS, callbacks(), LLM_CONFIG);

    expect(fetchMock.mock.calls[0][0]).not.toContain('sk-user');
    expect(fetchMock.mock.calls[0][0]).not.toContain('?');
  });

  it('без своего LLM поля не подставляются', async () => {
    const fetchMock = stubSse();

    await api.fixRegisters(REGISTERS, callbacks());

    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body.llm_api_url).toBeUndefined();
    expect(body.llm_api_key).toBeUndefined();
    expect(body.registers).toHaveLength(1);
  });
});
