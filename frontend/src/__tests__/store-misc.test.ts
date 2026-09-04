import { describe, it, expect, beforeEach, vi } from 'vitest';
import { restoreLlmConfig, useStore } from '../store';
import { createTestRegister, createTestGroup, createTestDeviceInfo, resetFixtureCounter } from './fixtures';
import { resetMocks } from './setup';
import { importTemplate as importTemplateApi } from '../api';

function getState() {
  return useStore.getState();
}

beforeEach(() => {
  resetMocks();
  resetFixtureCounter();
  useStore.setState({
    registers: [],
    groups: [],
    deviceInfo: { name: '', id: '' },
    files: [],
    template: null,
    buildError: null,
    analyzeStatus: 'idle',
    analyzeProgress: null,
    analyzeError: null,
    highlightedRegisterId: null,
    expandedRows: new Set(),
    previewLang: 'en',
    llmConfig: {},
  });
});

describe('resetAll', () => {
  it('сбрасывает регистры, группы, deviceInfo', () => {
    const reg = createTestRegister({ id: 'r1' });
    const group = createTestGroup({ id: 'g1' });
    useStore.setState({
      registers: [reg],
      groups: [group],
      deviceInfo: createTestDeviceInfo({ name: 'Device' }),
    });

    getState().resetAll();

    expect(getState().registers).toEqual([]);
    expect(getState().groups).toEqual([]);
    expect(getState().deviceInfo).toEqual({ name: '', id: '' });
  });

  it('сбрасывает файлы и шаблон', () => {
    useStore.setState({
      files: [new File([''], 'test.pdf')],
      template: { device_type: 'test' } as never,
    });

    getState().resetAll();

    expect(getState().files).toEqual([]);
    expect(getState().template).toBeNull();
  });

  it('сбрасывает UI-состояние', () => {
    useStore.setState({
      highlightedRegisterId: 'r1',
      expandedRows: new Set(['r1', 'r2']),
      analyzeStatus: 'error',
      analyzeError: 'Some error',
      buildError: 'Build error',
      previewLang: 'ru',
    });

    getState().resetAll();

    expect(getState().highlightedRegisterId).toBeNull();
    expect(getState().expandedRows.size).toBe(0);
    expect(getState().analyzeStatus).toBe('idle');
    expect(getState().analyzeError).toBeNull();
    expect(getState().buildError).toBeNull();
    expect(getState().previewLang).toBe('en');
  });

  it('сохраняет llmConfig', () => {
    useStore.setState({ llmConfig: { apiUrl: 'http://test', model: 'gpt-4' } });

    getState().resetAll();

    expect(getState().llmConfig).toEqual({ apiUrl: 'http://test', model: 'gpt-4' });
  });

  it('сохраняет очищенное состояние в localStorage', () => {
    const reg = createTestRegister({ id: 'r1' });
    useStore.setState({ registers: [reg] });

    getState().resetAll();

    const stored = JSON.parse(localStorage.getItem('wb-template-state')!);
    expect(stored.registers).toEqual([]);
    expect(stored.groups).toEqual([]);
  });
});

describe('setDeviceInfo', () => {
  it('обновляет поля deviceInfo (merge)', () => {
    useStore.setState({ deviceInfo: { name: 'Old', id: 'old-id' } });

    getState().setDeviceInfo({ name: 'New Device' });

    expect(getState().deviceInfo.name).toBe('New Device');
    expect(getState().deviceInfo.id).toBe('old-id'); // не затронуто
  });

  it('добавляет новые поля', () => {
    useStore.setState({ deviceInfo: { name: 'Dev', id: 'dev' } });

    getState().setDeviceInfo({ device_group: 'relays', max_read_registers: 10 });

    expect(getState().deviceInfo.device_group).toBe('relays');
    expect(getState().deviceInfo.max_read_registers).toBe(10);
  });
});

describe('файлы', () => {
  it('setFiles — заменяет файлы', () => {
    const f1 = new File(['a'], 'a.pdf');
    const f2 = new File(['b'], 'b.pdf');

    getState().setFiles([f1, f2]);
    expect(getState().files).toHaveLength(2);
  });

  it('addFiles — добавляет файлы к существующим', () => {
    const f1 = new File(['a'], 'a.pdf');
    getState().setFiles([f1]);

    const f2 = new File(['b'], 'b.pdf');
    getState().addFiles([f2]);

    expect(getState().files).toHaveLength(2);
  });

  it('removeFile — удаляет файл по индексу', () => {
    const f1 = new File(['a'], 'a.pdf');
    const f2 = new File(['b'], 'b.pdf');
    const f3 = new File(['c'], 'c.pdf');
    getState().setFiles([f1, f2, f3]);

    getState().removeFile(1);

    expect(getState().files).toHaveLength(2);
    expect(getState().files[0].name).toBe('a.pdf');
    expect(getState().files[1].name).toBe('c.pdf');
  });
});

describe('setLlmConfig', () => {
  it('мержит новые поля в llmConfig', () => {
    useStore.setState({ llmConfig: { apiUrl: 'http://old' } });

    getState().setLlmConfig({ model: 'gpt-4' });

    expect(getState().llmConfig.apiUrl).toBe('http://old');
    expect(getState().llmConfig.model).toBe('gpt-4');
  });
});

describe('setPreviewLang', () => {
  it('устанавливает язык превью', () => {
    getState().setPreviewLang('ru');
    expect(getState().previewLang).toBe('ru');
  });
});

describe('customSystemPrompt', () => {
  it('setCustomSystemPrompt сохраняет в localStorage', () => {
    getState().setCustomSystemPrompt('Custom prompt');

    expect(getState().customSystemPrompt).toBe('Custom prompt');
    expect(localStorage.getItem('wb-template-custom-prompt')).toBe('Custom prompt');
  });

  it('setCustomSystemPrompt(null) удаляет из localStorage', () => {
    getState().setCustomSystemPrompt('Test');
    getState().setCustomSystemPrompt(null);

    expect(getState().customSystemPrompt).toBeNull();
    expect(localStorage.getItem('wb-template-custom-prompt')).toBeNull();
  });
});

describe('importTemplate', () => {
  it('устанавливает importing=true на время импорта', async () => {
    const states: boolean[] = [];
    // Мок, который фиксирует importing в момент вызова
    vi.mocked(importTemplateApi).mockImplementation(async () => {
      states.push(getState().importing);
      return { registers: [], groups: [], device_info: { name: '', id: '' } };
    });

    expect(getState().importing).toBe(false);
    await getState().importTemplate(new File(['{}'], 'test.json'));
    expect(states[0]).toBe(true); // во время вызова API
    expect(getState().importing).toBe(false); // после завершения
  });

  it('при ошибке API сохраняет importError и сбрасывает importing', async () => {
    vi.mocked(importTemplateApi).mockRejectedValue(new Error('Not a wb-mqtt-serial template'));

    await getState().importTemplate(new File(['{}'], 'bad.json'));

    expect(getState().importing).toBe(false);
    expect(getState().importError).toBe('Not a wb-mqtt-serial template');
  });

  it('сбрасывает importError при повторном импорте', async () => {
    useStore.setState({ importError: 'Previous error' });
    vi.mocked(importTemplateApi).mockResolvedValue({
      registers: [], groups: [], device_info: { name: '', id: '' },
    });

    await getState().importTemplate(new File(['{}'], 'good.json'));

    expect(getState().importError).toBeNull();
  });
});

describe('restoreLlmConfig', () => {
  it('зажимает сохранённую температуру в 0..2 — прежнее поле пускало больше', () => {
    expect(restoreLlmConfig({ temperature: 7 }).temperature).toBe(2);
    expect(restoreLlmConfig({ temperature: -1 }).temperature).toBe(0);
  });

  it('валидное значение и пустой конфиг не трогает', () => {
    expect(restoreLlmConfig({ temperature: 0.7 }).temperature).toBe(0.7);
    expect(restoreLlmConfig(undefined)).toEqual({});
  });
});
