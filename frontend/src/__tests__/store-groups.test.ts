import { describe, it, expect, beforeEach } from 'vitest';
import { useStore } from '../store';
import { createTestGroup, resetFixtureCounter } from './fixtures';
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

describe('addGroup', () => {
  it('добавляет группу в конец', () => {
    const g = createTestGroup({ id: 'g1', title: 'Sensors' });
    getState().addGroup(g);

    expect(getState().groups).toHaveLength(1);
    expect(getState().groups[0]).toEqual(g);
  });

  it('сохраняет порядок добавления', () => {
    const g1 = createTestGroup({ id: 'g1', title: 'First', order: 0 });
    const g2 = createTestGroup({ id: 'g2', title: 'Second', order: 1 });
    getState().addGroup(g1);
    getState().addGroup(g2);

    expect(getState().groups).toHaveLength(2);
    expect(getState().groups[0].id).toBe('g1');
    expect(getState().groups[1].id).toBe('g2');
  });
});

describe('updateGroup', () => {
  it('обновляет поля группы по ID', () => {
    const g = createTestGroup({ id: 'g1', title: 'Old', order: 0 });
    useStore.setState({ groups: [g] });

    getState().updateGroup('g1', { title: 'New' });

    expect(getState().groups[0].title).toBe('New');
    expect(getState().groups[0].order).toBe(0); // не затронуто
  });

  it('не затрагивает другие группы', () => {
    const g1 = createTestGroup({ id: 'g1', title: 'A' });
    const g2 = createTestGroup({ id: 'g2', title: 'B' });
    useStore.setState({ groups: [g1, g2] });

    getState().updateGroup('g1', { title: 'Updated' });

    expect(getState().groups[0].title).toBe('Updated');
    expect(getState().groups[1].title).toBe('B');
  });

  it('обновляет переводы группы', () => {
    const g = createTestGroup({ id: 'g1', title: 'General' });
    useStore.setState({ groups: [g] });

    getState().updateGroup('g1', {
      translations: { ru: { title: 'Общие' } },
    });

    expect(getState().groups[0].translations).toEqual({ ru: { title: 'Общие' } });
  });
});

describe('removeGroup', () => {
  it('удаляет группу по ID', () => {
    const g1 = createTestGroup({ id: 'g1' });
    const g2 = createTestGroup({ id: 'g2' });
    useStore.setState({ groups: [g1, g2] });

    getState().removeGroup('g1');

    expect(getState().groups).toHaveLength(1);
    expect(getState().groups[0].id).toBe('g2');
  });

  it('не падает при удалении несуществующей группы', () => {
    const g = createTestGroup({ id: 'g1' });
    useStore.setState({ groups: [g] });

    getState().removeGroup('nonexistent');
    expect(getState().groups).toHaveLength(1);
  });
});

describe('setGroups', () => {
  it('полностью заменяет массив групп', () => {
    const old = createTestGroup({ id: 'old' });
    useStore.setState({ groups: [old] });

    const newGroups = [
      createTestGroup({ id: 'new1', order: 0 }),
      createTestGroup({ id: 'new2', order: 1 }),
    ];
    getState().setGroups(newGroups);

    expect(getState().groups).toHaveLength(2);
    expect(getState().groups[0].id).toBe('new1');
    expect(getState().groups[1].id).toBe('new2');
  });
});
