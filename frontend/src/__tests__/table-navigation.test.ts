import { describe, it, expect } from 'vitest';
import { nextField, deleteTargets } from '../utils/tableNavigation';

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
  it('отмеченные чекбоксами строки удаляются все', () => {
    const targets = deleteTargets(new Set(['a', 'b']), null);
    expect(targets).toEqual(new Set(['a', 'b']));
  });

  it('без отметок удаляется подсвеченная строка', () => {
    expect(deleteTargets(new Set(), 'c')).toEqual(new Set(['c']));
  });

  // Отметки чекбоксами приоритетнее: подсветка ставится любым кликом по строке,
  // поэтому она почти всегда есть и сама по себе не выражает намерения удалить
  it('при отметках подсветка не влияет на набор', () => {
    expect(deleteTargets(new Set(['a']), 'c')).toEqual(new Set(['a']));
  });

  it('когда удалять нечего — null, клавиша достаётся браузеру', () => {
    expect(deleteTargets(new Set(), null)).toBeNull();
  });

  it('возвращается копия, а не сам набор выбранных строк', () => {
    const selected = new Set(['a']);
    const targets = deleteTargets(selected, null);
    expect(targets).not.toBe(selected);
  });
});
