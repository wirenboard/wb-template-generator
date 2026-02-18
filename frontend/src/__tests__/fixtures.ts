import type { Register, RegisterGroup, DeviceInfo } from '../types';

let counter = 0;

/** Создаёт тестовый регистр с дефолтами и возможностью переопределения */
export function createTestRegister(overrides: Partial<Register> = {}): Register {
  counter++;
  return {
    id: `test-reg-${counter}`,
    address: counter,
    name: `Register ${counter}`,
    reg_type: 'holding',
    format: 'u16',
    scale: 1,
    offset: 0,
    access: 'read',
    channel_type: 'value',
    group: 'general',
    is_parameter: false,
    enabled: true,
    translations: {},
    ...overrides,
  };
}

/** Создаёт тестовую группу */
export function createTestGroup(overrides: Partial<RegisterGroup> = {}): RegisterGroup {
  counter++;
  return {
    id: `test-group-${counter}`,
    title: `Group ${counter}`,
    order: counter,
    translations: {},
    ...overrides,
  };
}

/** Создаёт тестовый DeviceInfo */
export function createTestDeviceInfo(overrides: Partial<DeviceInfo> = {}): DeviceInfo {
  return {
    name: 'Test Device',
    id: 'test-device',
    ...overrides,
  };
}

/** Сброс счётчика (вызывать в beforeEach) */
export function resetFixtureCounter() {
  counter = 0;
}
