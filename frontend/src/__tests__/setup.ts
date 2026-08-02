import { vi } from 'vitest';

// Мок localStorage
const storage = new Map<string, string>();
const localStorageMock: Storage = {
  getItem: (key: string) => storage.get(key) ?? null,
  setItem: (key: string, value: string) => { storage.set(key, value); },
  removeItem: (key: string) => { storage.delete(key); },
  clear: () => storage.clear(),
  get length() { return storage.size; },
  key: (index: number) => [...storage.keys()][index] ?? null,
};
vi.stubGlobal('localStorage', localStorageMock);

// Мок crypto.randomUUID
let uuidCounter = 0;
vi.stubGlobal('crypto', {
  randomUUID: () => `uuid-${++uuidCounter}`,
});

// Сброс между тестами
export function resetMocks() {
  storage.clear();
  uuidCounter = 0;
}

// Мок import.meta.hot
vi.stubGlobal('import', { meta: { hot: undefined } });

// Мок api.ts — все функции заглушки
vi.mock('../api', () => ({
  buildTemplate: vi.fn().mockResolvedValue(null),
  analyzeFiles: vi.fn(),
  fetchStatus: vi.fn().mockResolvedValue({ llm_available: true, max_file_size_mb: 2, server_model: null }),
  translateStrings: vi.fn().mockResolvedValue({}),
  importTemplate: vi.fn().mockResolvedValue({ registers: [], groups: [], device_info: { name: '', id: '' } }),
}));
