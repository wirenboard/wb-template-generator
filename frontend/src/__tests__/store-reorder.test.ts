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
    template: null,
    buildError: null,
  });
});

describe('reorderRegister', () => {
  it('перемещает регистр перед целью (before) внутри группы', () => {
    const r1 = createTestRegister({ id: 'r1', name: 'A', group: 'g1' });
    const r2 = createTestRegister({ id: 'r2', name: 'B', group: 'g1' });
    const r3 = createTestRegister({ id: 'r3', name: 'C', group: 'g1' });
    useStore.setState({ registers: [r1, r2, r3] });

    // Перемещаем r3 перед r1: ожидаем [r3, r1, r2]
    getState().reorderRegister('r3', 'r1', 'before');
    const ids = getState().registers.map((r) => r.id);

    expect(ids).toEqual(['r3', 'r1', 'r2']);
  });

  it('перемещает регистр после цели (after) внутри группы', () => {
    const r1 = createTestRegister({ id: 'r1', name: 'A', group: 'g1' });
    const r2 = createTestRegister({ id: 'r2', name: 'B', group: 'g1' });
    const r3 = createTestRegister({ id: 'r3', name: 'C', group: 'g1' });
    useStore.setState({ registers: [r1, r2, r3] });

    // Перемещаем r1 после r3: ожидаем [r2, r3, r1]
    getState().reorderRegister('r1', 'r3', 'after');
    const ids = getState().registers.map((r) => r.id);

    expect(ids).toEqual(['r2', 'r3', 'r1']);
  });

  it('перемещает регистр между группами (меняет group)', () => {
    const r1 = createTestRegister({ id: 'r1', group: 'g1' });
    const r2 = createTestRegister({ id: 'r2', group: 'g2' });
    useStore.setState({ registers: [r1, r2] });

    getState().reorderRegister('r1', 'r2', 'before');
    const moved = getState().registers.find((r) => r.id === 'r1')!;

    expect(moved.group).toBe('g2');
  });

  it('сбрасывает param_order при перемещении', () => {
    const r1 = createTestRegister({ id: 'r1', group: 'g1', param_order: 5 });
    const r2 = createTestRegister({ id: 'r2', group: 'g1' });
    useStore.setState({ registers: [r1, r2] });

    getState().reorderRegister('r1', 'r2', 'after');
    const moved = getState().registers.find((r) => r.id === 'r1')!;

    expect(moved.param_order).toBeUndefined();
  });

  it('ничего не делает если draggedId === targetId', () => {
    const r1 = createTestRegister({ id: 'r1' });
    const r2 = createTestRegister({ id: 'r2' });
    useStore.setState({ registers: [r1, r2] });

    getState().reorderRegister('r1', 'r1', 'before');
    const ids = getState().registers.map((r) => r.id);

    expect(ids).toEqual(['r1', 'r2']);
  });

  it('ничего не делает при несуществующем draggedId', () => {
    const r1 = createTestRegister({ id: 'r1' });
    useStore.setState({ registers: [r1] });

    getState().reorderRegister('nonexistent', 'r1', 'before');
    expect(getState().registers).toHaveLength(1);
  });

  it('перемещает первый регистр после последнего', () => {
    const r1 = createTestRegister({ id: 'r1', group: 'g1' });
    const r2 = createTestRegister({ id: 'r2', group: 'g1' });
    const r3 = createTestRegister({ id: 'r3', group: 'g1' });
    const r4 = createTestRegister({ id: 'r4', group: 'g1' });
    useStore.setState({ registers: [r1, r2, r3, r4] });

    getState().reorderRegister('r1', 'r4', 'after');
    const ids = getState().registers.map((r) => r.id);

    expect(ids).toEqual(['r2', 'r3', 'r4', 'r1']);
  });

  it('перемещает последний регистр перед первым', () => {
    const r1 = createTestRegister({ id: 'r1', group: 'g1' });
    const r2 = createTestRegister({ id: 'r2', group: 'g1' });
    const r3 = createTestRegister({ id: 'r3', group: 'g1' });
    useStore.setState({ registers: [r1, r2, r3] });

    getState().reorderRegister('r3', 'r1', 'before');
    const ids = getState().registers.map((r) => r.id);

    expect(ids).toEqual(['r3', 'r1', 'r2']);
  });
});

describe('moveRegistersToGroup', () => {
  it('перемещает один регистр в другую группу', () => {
    const r1 = createTestRegister({ id: 'r1', group: 'g1' });
    useStore.setState({ registers: [r1] });

    getState().moveRegistersToGroup(['r1'], 'g2');

    expect(getState().registers[0].group).toBe('g2');
  });

  it('перемещает несколько регистров', () => {
    const r1 = createTestRegister({ id: 'r1', group: 'g1' });
    const r2 = createTestRegister({ id: 'r2', group: 'g1' });
    const r3 = createTestRegister({ id: 'r3', group: 'g2' });
    useStore.setState({ registers: [r1, r2, r3] });

    getState().moveRegistersToGroup(['r1', 'r2'], 'g3');

    expect(getState().registers[0].group).toBe('g3');
    expect(getState().registers[1].group).toBe('g3');
    expect(getState().registers[2].group).toBe('g2'); // не затронут
  });

  it('не затрагивает регистры не из списка', () => {
    const r1 = createTestRegister({ id: 'r1', group: 'g1' });
    const r2 = createTestRegister({ id: 'r2', group: 'g1' });
    useStore.setState({ registers: [r1, r2] });

    getState().moveRegistersToGroup(['r1'], 'g2');

    expect(getState().registers[0].group).toBe('g2');
    expect(getState().registers[1].group).toBe('g1');
  });

  it('сохраняет порядок регистров в массиве', () => {
    const r1 = createTestRegister({ id: 'r1', group: 'g1' });
    const r2 = createTestRegister({ id: 'r2', group: 'g1' });
    const r3 = createTestRegister({ id: 'r3', group: 'g1' });
    useStore.setState({ registers: [r1, r2, r3] });

    getState().moveRegistersToGroup(['r2'], 'g2');
    const ids = getState().registers.map((r) => r.id);

    expect(ids).toEqual(['r1', 'r2', 'r3']);
  });
});
