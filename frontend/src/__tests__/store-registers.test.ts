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
    lastActiveGroup: 'general',
    newlyAddedRegisterId: null,
    expandedRows: new Set(),
    template: null,
    buildError: null,
  });
});

describe('addRegister', () => {
  it('создаёт регистр с дефолтными значениями', () => {
    getState().addRegister();
    const regs = getState().registers;

    expect(regs).toHaveLength(1);
    expect(regs[0].name).toBe('New Register');
    expect(regs[0].reg_type).toBe('holding');
    expect(regs[0].format).toBe('u16');
    expect(regs[0].scale).toBe(1);
    expect(regs[0].offset).toBe(0);
    expect(regs[0].access).toBe('read');
    expect(regs[0].channel_type).toBe('value');
    expect(regs[0].is_parameter).toBe(false);
    expect(regs[0].enabled).toBe(true);
  });

  it('присваивает UUID', () => {
    getState().addRegister();
    expect(getState().registers[0].id).toBe('uuid-1');
  });

  it('привязывает к lastActiveGroup', () => {
    useStore.setState({ lastActiveGroup: 'sensors' });
    getState().addRegister();
    expect(getState().registers[0].group).toBe('sensors');
  });

  it('устанавливает newlyAddedRegisterId', () => {
    getState().addRegister();
    expect(getState().newlyAddedRegisterId).toBe('uuid-1');
  });

  it('добавляет несколько регистров с уникальными ID', () => {
    getState().addRegister();
    getState().addRegister();
    const regs = getState().registers;

    expect(regs).toHaveLength(2);
    expect(regs[0].id).not.toBe(regs[1].id);
  });
});

describe('updateRegister', () => {
  it('обновляет поля регистра по ID', () => {
    const reg = createTestRegister({ id: 'r1', name: 'Old' });
    useStore.setState({ registers: [reg] });

    getState().updateRegister('r1', { name: 'New', scale: 10 });
    const updated = getState().registers[0];

    expect(updated.name).toBe('New');
    expect(updated.scale).toBe(10);
    expect(updated.format).toBe('u16'); // не затронуто
  });

  it('не затрагивает другие регистры', () => {
    const r1 = createTestRegister({ id: 'r1', name: 'First' });
    const r2 = createTestRegister({ id: 'r2', name: 'Second' });
    useStore.setState({ registers: [r1, r2] });

    getState().updateRegister('r1', { name: 'Updated' });

    expect(getState().registers[0].name).toBe('Updated');
    expect(getState().registers[1].name).toBe('Second');
  });

  it('ничего не ломает при несуществующем ID', () => {
    const reg = createTestRegister({ id: 'r1' });
    useStore.setState({ registers: [reg] });

    getState().updateRegister('nonexistent', { name: 'X' });
    expect(getState().registers).toHaveLength(1);
    expect(getState().registers[0].name).toBe(reg.name);
  });
});

describe('removeRegister', () => {
  it('удаляет регистр по ID', () => {
    const r1 = createTestRegister({ id: 'r1' });
    const r2 = createTestRegister({ id: 'r2' });
    useStore.setState({ registers: [r1, r2] });

    getState().removeRegister('r1');

    expect(getState().registers).toHaveLength(1);
    expect(getState().registers[0].id).toBe('r2');
  });

  it('не падает при удалении несуществующего', () => {
    const reg = createTestRegister({ id: 'r1' });
    useStore.setState({ registers: [reg] });

    getState().removeRegister('nonexistent');
    expect(getState().registers).toHaveLength(1);
  });
});

describe('toggleRegister', () => {
  it('переключает enabled false→true', () => {
    const reg = createTestRegister({ id: 'r1', enabled: false });
    useStore.setState({ registers: [reg] });

    getState().toggleRegister('r1');
    expect(getState().registers[0].enabled).toBe(true);
  });

  it('переключает enabled true→false', () => {
    const reg = createTestRegister({ id: 'r1', enabled: true });
    useStore.setState({ registers: [reg] });

    getState().toggleRegister('r1');
    expect(getState().registers[0].enabled).toBe(false);
  });

  it('не затрагивает другие регистры', () => {
    const r1 = createTestRegister({ id: 'r1', enabled: true });
    const r2 = createTestRegister({ id: 'r2', enabled: true });
    useStore.setState({ registers: [r1, r2] });

    getState().toggleRegister('r1');

    expect(getState().registers[0].enabled).toBe(false);
    expect(getState().registers[1].enabled).toBe(true);
  });
});

describe('setRegisters', () => {
  it('полностью заменяет массив регистров', () => {
    const old = createTestRegister({ id: 'old' });
    useStore.setState({ registers: [old] });

    const newRegs = [
      createTestRegister({ id: 'new1' }),
      createTestRegister({ id: 'new2' }),
    ];
    getState().setRegisters(newRegs);

    expect(getState().registers).toHaveLength(2);
    expect(getState().registers[0].id).toBe('new1');
    expect(getState().registers[1].id).toBe('new2');
  });
});
