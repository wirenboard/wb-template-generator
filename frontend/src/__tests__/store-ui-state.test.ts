import { describe, it, expect, beforeEach } from 'vitest';
import { useStore } from '../store';
import { createTestRegister, createTestGroup, resetFixtureCounter } from './fixtures';
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
    expandedRows: new Set(),
    collapsedGroups: new Set(),
    highlightedRegisterId: null,
    lastActiveGroup: 'general',
    template: null,
    buildError: null,
  });
});

describe('toggleRowExpanded', () => {
  it('раскрывает строку', () => {
    getState().toggleRowExpanded('r1');
    expect(getState().expandedRows.has('r1')).toBe(true);
  });

  it('сворачивает уже раскрытую строку', () => {
    useStore.setState({ expandedRows: new Set(['r1']) });
    getState().toggleRowExpanded('r1');
    expect(getState().expandedRows.has('r1')).toBe(false);
  });

  it('не затрагивает другие строки', () => {
    useStore.setState({ expandedRows: new Set(['r1']) });
    getState().toggleRowExpanded('r2');
    expect(getState().expandedRows.has('r1')).toBe(true);
    expect(getState().expandedRows.has('r2')).toBe(true);
  });
});

describe('setRowExpanded', () => {
  it('раскрывает строку (expanded=true)', () => {
    getState().setRowExpanded('r1', true);
    expect(getState().expandedRows.has('r1')).toBe(true);
  });

  it('сворачивает строку (expanded=false)', () => {
    useStore.setState({ expandedRows: new Set(['r1']) });
    getState().setRowExpanded('r1', false);
    expect(getState().expandedRows.has('r1')).toBe(false);
  });

  it('идемпотентно — повторное раскрытие не ломает', () => {
    getState().setRowExpanded('r1', true);
    getState().setRowExpanded('r1', true);
    expect(getState().expandedRows.has('r1')).toBe(true);
  });
});

describe('toggleGroupCollapsed', () => {
  it('сворачивает группу', () => {
    getState().toggleGroupCollapsed('g1');
    expect(getState().collapsedGroups.has('g1')).toBe(true);
  });

  it('разворачивает свёрнутую группу', () => {
    useStore.setState({ collapsedGroups: new Set(['g1']) });
    getState().toggleGroupCollapsed('g1');
    expect(getState().collapsedGroups.has('g1')).toBe(false);
  });
});

describe('collapseAllGroups', () => {
  it('сворачивает все группы из groups[]', () => {
    const g1 = createTestGroup({ id: 'g1' });
    const g2 = createTestGroup({ id: 'g2' });
    useStore.setState({ groups: [g1, g2] });

    getState().collapseAllGroups();

    expect(getState().collapsedGroups.has('g1')).toBe(true);
    expect(getState().collapsedGroups.has('g2')).toBe(true);
  });

  it('включает группы из регистров, не представленные в groups[]', () => {
    const reg = createTestRegister({ id: 'r1', group: 'orphan-group' });
    useStore.setState({ registers: [reg], groups: [] });

    getState().collapseAllGroups();

    expect(getState().collapsedGroups.has('orphan-group')).toBe(true);
  });
});

describe('expandAllGroups', () => {
  it('разворачивает все группы', () => {
    useStore.setState({ collapsedGroups: new Set(['g1', 'g2', 'g3']) });

    getState().expandAllGroups();

    expect(getState().collapsedGroups.size).toBe(0);
  });
});

describe('setHighlightedRegister', () => {
  it('устанавливает highlightedRegisterId', () => {
    getState().setHighlightedRegister('r1');
    expect(getState().highlightedRegisterId).toBe('r1');
  });

  it('обновляет lastActiveGroup по группе регистра', () => {
    const reg = createTestRegister({ id: 'r1', group: 'sensors' });
    useStore.setState({ registers: [reg] });

    getState().setHighlightedRegister('r1');

    expect(getState().lastActiveGroup).toBe('sensors');
  });

  it('не меняет lastActiveGroup если регистр не найден', () => {
    useStore.setState({ lastActiveGroup: 'general' });

    getState().setHighlightedRegister('nonexistent');

    expect(getState().lastActiveGroup).toBe('general');
  });

  it('сбрасывает подсветку при null', () => {
    getState().setHighlightedRegister('r1');
    getState().setHighlightedRegister(null);

    expect(getState().highlightedRegisterId).toBeNull();
  });
});
