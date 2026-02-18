import { describe, it, expect, beforeEach } from 'vitest';
import { useStore } from '../store';
import { createTestRegister, createTestGroup, createTestDeviceInfo, resetFixtureCounter } from './fixtures';
import { resetMocks } from './setup';

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
