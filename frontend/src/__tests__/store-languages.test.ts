import { describe, it, expect, beforeEach } from 'vitest';
import { useStore } from '../store';
import { createTestRegister, resetFixtureCounter } from './fixtures';
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
    languages: [{ code: 'ru', label: 'Русский (ru)' }],
    template: null,
    buildError: null,
  });
});

describe('addLanguage', () => {
  it('добавляет новый язык', () => {
    getState().addLanguage({ code: 'de', label: 'German' });

    expect(getState().languages).toHaveLength(2);
    expect(getState().languages[1]).toEqual({ code: 'de', label: 'German' });
  });

  it('не добавляет дубликат по коду', () => {
    getState().addLanguage({ code: 'ru', label: 'Russian (duplicate)' });

    expect(getState().languages).toHaveLength(1);
    expect(getState().languages[0].label).toBe('Русский (ru)');
  });

  it('сохраняет в localStorage', () => {
    getState().addLanguage({ code: 'fr', label: 'French' });

    const stored = JSON.parse(localStorage.getItem('wb-template-languages')!);
    expect(stored).toHaveLength(2);
    expect(stored[1].code).toBe('fr');
  });
});

describe('removeLanguage', () => {
  it('удаляет язык по коду', () => {
    getState().addLanguage({ code: 'de', label: 'German' });
    getState().removeLanguage('de');

    expect(getState().languages).toHaveLength(1);
    expect(getState().languages[0].code).toBe('ru');
  });

  it('не падает при удалении несуществующего', () => {
    getState().removeLanguage('nonexistent');
    expect(getState().languages).toHaveLength(1);
  });

  it('обновляет localStorage', () => {
    getState().addLanguage({ code: 'de', label: 'German' });
    getState().removeLanguage('de');

    const stored = JSON.parse(localStorage.getItem('wb-template-languages')!);
    expect(stored).toHaveLength(1);
  });
});

describe('setLanguages', () => {
  it('полностью заменяет список языков', () => {
    const langs = [
      { code: 'de', label: 'German' },
      { code: 'fr', label: 'French' },
    ];
    getState().setLanguages(langs);

    expect(getState().languages).toEqual(langs);
  });

  it('сохраняет в localStorage', () => {
    const langs = [{ code: 'zh', label: 'Chinese' }];
    getState().setLanguages(langs);

    const stored = JSON.parse(localStorage.getItem('wb-template-languages')!);
    expect(stored).toEqual(langs);
  });
});

describe('propagateEnumTranslation', () => {
  it('обновляет перевод enum по всем регистрам с тем же title', () => {
    const r1 = createTestRegister({
      id: 'r1',
      enum_entries: [
        { value: 0, title: 'Off' },
        { value: 1, title: 'On' },
      ],
    });
    const r2 = createTestRegister({
      id: 'r2',
      enum_entries: [
        { value: 0, title: 'Off' },
        { value: 1, title: 'Auto' },
      ],
    });
    useStore.setState({ registers: [r1, r2] });

    getState().propagateEnumTranslation('Off', 'ru', 'Выкл');

    const regs = getState().registers;
    // r1 — первый entry (Off) обновлён
    expect(regs[0].enum_entries![0].translations).toEqual({ ru: 'Выкл' });
    // r1 — второй entry (On) не затронут
    expect(regs[0].enum_entries![1].translations).toBeUndefined();
    // r2 — первый entry (Off) тоже обновлён
    expect(regs[1].enum_entries![0].translations).toEqual({ ru: 'Выкл' });
    // r2 — второй entry (Auto) не затронут
    expect(regs[1].enum_entries![1].translations).toBeUndefined();
  });

  it('не затрагивает регистры без enum_entries', () => {
    const r1 = createTestRegister({ id: 'r1' }); // нет enum_entries
    const r2 = createTestRegister({
      id: 'r2',
      enum_entries: [{ value: 0, title: 'Off' }],
    });
    useStore.setState({ registers: [r1, r2] });

    getState().propagateEnumTranslation('Off', 'ru', 'Выкл');

    expect(getState().registers[0].enum_entries).toBeUndefined();
    expect(getState().registers[1].enum_entries![0].translations).toEqual({ ru: 'Выкл' });
  });

  it('удаляет перевод если передана пустая строка', () => {
    const reg = createTestRegister({
      id: 'r1',
      enum_entries: [{ value: 0, title: 'Off', translations: { ru: 'Выкл' } }],
    });
    useStore.setState({ registers: [reg] });

    getState().propagateEnumTranslation('Off', 'ru', '');

    const entry = getState().registers[0].enum_entries![0];
    expect(entry.translations).toBeUndefined();
  });

  it('не обновляет если перевод уже такой же', () => {
    const reg = createTestRegister({
      id: 'r1',
      enum_entries: [{ value: 0, title: 'Off', translations: { ru: 'Выкл' } }],
    });
    useStore.setState({ registers: [reg] });
    const before = getState().registers;

    getState().propagateEnumTranslation('Off', 'ru', 'Выкл');

    // Store не должен создавать новые ссылки если данные не изменились
    expect(getState().registers).toBe(before);
  });
});
