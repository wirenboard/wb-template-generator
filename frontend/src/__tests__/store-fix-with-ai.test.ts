import { describe, it, expect, beforeEach, vi } from 'vitest';
import { useStore } from '../store';
import { fixRegisters as fixRegistersApi } from '../api';
import { resetMocks } from './setup';

// Кнопка «Исправить через AI» обязана идти на тот LLM, который настроил пользователь

const REGISTERS = [
  { id: 'r0', address: 70000, name: 'Bad', reg_type: 'holding', format: 'u16' },
] as never;

function getState() {
  return useStore.getState();
}

beforeEach(() => {
  resetMocks();
  vi.mocked(fixRegistersApi).mockReset();
  useStore.setState({ registers: REGISTERS, fixingWithAi: false, llmConfig: {} });
});

describe('fixWithAi', () => {
  it('передаёт настройки своего LLM в api', () => {
    const llmConfig = { apiUrl: 'https://user.example/v1', apiKey: 'sk-user', model: 'local' };
    useStore.setState({ llmConfig });

    getState().fixWithAi();

    expect(fixRegistersApi).toHaveBeenCalledTimes(1);
    // Третий аргумент — настройки LLM, именно его и забывали
    expect(vi.mocked(fixRegistersApi).mock.calls[0][2]).toEqual(llmConfig);
  });

  it('передаёт текущие регистры первым аргументом', () => {
    getState().fixWithAi();

    expect(vi.mocked(fixRegistersApi).mock.calls[0][0]).toHaveLength(1);
  });

  it('без настроек LLM зовёт api с пустым конфигом, а не падает', () => {
    getState().fixWithAi();

    expect(vi.mocked(fixRegistersApi).mock.calls[0][2]).toEqual({});
  });

  it('повторный вызов во время исправления игнорируется', () => {
    useStore.setState({ fixingWithAi: true });

    getState().fixWithAi();

    expect(fixRegistersApi).not.toHaveBeenCalled();
  });

  it('без регистров запрос не уходит', () => {
    useStore.setState({ registers: [] });

    getState().fixWithAi();

    expect(fixRegistersApi).not.toHaveBeenCalled();
  });

  it('ошибка из api попадает в состояние и снимает флаг', () => {
    vi.mocked(fixRegistersApi).mockImplementation((_regs, cb) => {
      cb.onError('провайдер LLM не принял ключ');
      return Promise.resolve();
    });

    getState().fixWithAi();

    expect(getState().fixWithAiError).toBe('провайдер LLM не принял ключ');
    expect(getState().fixingWithAi).toBe(false);
  });
});
