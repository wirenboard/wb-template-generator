import { describe, it, expect } from 'vitest';
import { nextField, deleteTargets, isTypingTarget, rowIdFromDomId } from '../utils/tableNavigation';

// Порядок колонок таблицы регистров — тот же, что в COLUMNS (RegisterTable.tsx)
const FIELDS = ['address', 'name', 'reg_type', 'format', 'units', 'channel_type', 'group'] as const;

describe('nextField', () => {
  it('Tab ведёт от «Адреса» к «Имени» — то, ради чего всё затевалось', () => {
    expect(nextField(FIELDS, 'address', 1)).toBe('name');
  });

  it('Shift+Tab возвращает от «Имени» к «Адресу»', () => {
    expect(nextField(FIELDS, 'name', -1)).toBe('address');
  });

  it('проходит всю строку вперёд без пропусков', () => {
    const visited: string[] = ['address'];
    let current: string | null = 'address';
    while (current) {
      current = nextField(FIELDS as readonly string[], current, 1);
      if (current) visited.push(current);
    }
    expect(visited).toEqual([...FIELDS]);
  });

  it('проходит всю строку назад без пропусков', () => {
    const visited: string[] = ['group'];
    let current: string | null = 'group';
    while (current) {
      current = nextField(FIELDS as readonly string[], current, -1);
      if (current) visited.push(current);
    }
    expect(visited).toEqual([...FIELDS].reverse());
  });

  // null означает «уводим фокус за пределы редактируемых колонок»:
  // вперёд — на чекбокс R/O, назад — на чекбокс «Вкл»
  it('за правым краем колонок возвращает null', () => {
    expect(nextField(FIELDS, 'group', 1)).toBeNull();
  });

  it('за левым краем колонок возвращает null', () => {
    expect(nextField(FIELDS, 'address', -1)).toBeNull();
  });

  it('неизвестное поле не роняет навигацию', () => {
    expect(nextField(FIELDS as readonly string[], 'nonexistent', 1)).toBeNull();
    expect(nextField(FIELDS as readonly string[], 'nonexistent', -1)).toBeNull();
  });

  it('в строке из одной колонки оба направления упираются в край', () => {
    const single = ['address'] as const;
    expect(nextField(single, 'address', 1)).toBeNull();
    expect(nextField(single, 'address', -1)).toBeNull();
  });
});

describe('deleteTargets', () => {
  const alive = new Set(['a', 'b', 'c']);

  it('отмеченные чекбоксами строки удаляются все', () => {
    expect(deleteTargets(new Set(['a', 'b']), null, alive)).toEqual(new Set(['a', 'b']));
  });

  it('без отметок удаляется текущая строка', () => {
    expect(deleteTargets(new Set(), 'c', alive)).toEqual(new Set(['c']));
  });

  // Отметки чекбоксами приоритетнее: текущая строка задаётся фокусом или кликом
  // и есть почти всегда, поэтому сама по себе не выражает намерения удалить
  it('при отметках текущая строка не влияет на набор', () => {
    expect(deleteTargets(new Set(['a']), 'c', alive)).toEqual(new Set(['a']));
  });

  it('когда удалять нечего — null, клавиша достаётся браузеру', () => {
    expect(deleteTargets(new Set(), null, alive)).toBeNull();
  });

  it('возвращается копия, а не сам набор выбранных строк', () => {
    const selected = new Set(['a']);
    expect(deleteTargets(selected, null, alive)).not.toBe(selected);
  });

  // Строку отметили галкой, потом удалили кнопкой «x» — id остаётся в selected.
  // Раньше первое нажатие Delete уходило в пустоту вместо удаления текущей строки
  it('отметки на исчезнувших строках отбрасываются', () => {
    expect(deleteTargets(new Set(['ghost']), 'c', alive)).toEqual(new Set(['c']));
  });

  it('из отметок остаются только живые строки', () => {
    expect(deleteTargets(new Set(['a', 'ghost']), null, alive)).toEqual(new Set(['a']));
  });

  it('текущая строка, которой уже нет, не удаляется', () => {
    expect(deleteTargets(new Set(), 'ghost', alive)).toBeNull();
  });

  it('в пустой таблице удалять нечего', () => {
    expect(deleteTargets(new Set(['a']), 'a', new Set())).toBeNull();
  });
});

describe('isTypingTarget', () => {
  // Из-за этого случая Delete не срабатывал после отметки строк галками:
  // фокус остаётся на чекбоксе, а он тоже <input>
  it('чекбокс — не набор текста, клавиши строк работают', () => {
    expect(isTypingTarget({ tagName: 'INPUT', type: 'checkbox' })).toBe(false);
  });

  it('текстовое поле защищено', () => {
    expect(isTypingTarget({ tagName: 'INPUT', type: 'text' })).toBe(true);
    expect(isTypingTarget({ tagName: 'TEXTAREA' })).toBe(true);
  });

  it('список защищён — в нём идёт выбор значения', () => {
    expect(isTypingTarget({ tagName: 'SELECT' })).toBe(true);
  });

  it('input без указанного типа считается текстовым', () => {
    expect(isTypingTarget({ tagName: 'INPUT' })).toBe(true);
  });

  it('contenteditable защищён', () => {
    expect(isTypingTarget({ tagName: 'DIV', isContentEditable: true })).toBe(true);
  });

  it('кнопки и ячейки таблицы клавиши не перехватывают', () => {
    expect(isTypingTarget({ tagName: 'BUTTON' })).toBe(false);
    expect(isTypingTarget({ tagName: 'INPUT', type: 'button' })).toBe(false);
    expect(isTypingTarget({ tagName: 'SPAN' })).toBe(false);
    expect(isTypingTarget({ tagName: 'BODY' })).toBe(false);
  });

  it('регистр в tagName и type не важен', () => {
    expect(isTypingTarget({ tagName: 'input', type: 'CHECKBOX' })).toBe(false);
    expect(isTypingTarget({ tagName: 'input', type: 'Text' })).toBe(true);
  });
});

describe('rowIdFromDomId', () => {
  it('достаёт id регистра из id строки таблицы', () => {
    expect(rowIdFromDomId('reg-row-uuid-1')).toBe('uuid-1');
  });

  it('id с дефисами не обрезается', () => {
    expect(rowIdFromDomId('reg-row-3f2b1a-9c-44')).toBe('3f2b1a-9c-44');
  });

  it('чужой или пустой id — не строка таблицы', () => {
    expect(rowIdFromDomId('some-other-id')).toBeNull();
    expect(rowIdFromDomId('reg-row-')).toBeNull();
    expect(rowIdFromDomId('')).toBeNull();
    expect(rowIdFromDomId(null)).toBeNull();
    expect(rowIdFromDomId(undefined)).toBeNull();
  });
});
