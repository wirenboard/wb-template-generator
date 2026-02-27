import { describe, it, expect, beforeEach } from 'vitest';
import { findInvalidConditionIds } from '../utils/conditionValidation';
import { createTestRegister, resetFixtureCounter } from './fixtures';

beforeEach(() => {
  resetFixtureCounter();
});

describe('findInvalidConditionIds', () => {
  it('пустой массив — нет невалидных', () => {
    expect(findInvalidConditionIds([])).toEqual(new Set());
  });

  it('регистры без condition — нет невалидных', () => {
    const regs = [
      createTestRegister({ name: 'Voltage' }),
      createTestRegister({ name: 'Mode', is_parameter: true }),
    ];
    expect(findInvalidConditionIds(regs)).toEqual(new Set());
  });

  it('condition ссылается на параметр — валидно', () => {
    const param = createTestRegister({ name: 'Relay Mode', is_parameter: true });
    const channel = createTestRegister({ name: 'Timer Value', condition: 'relay_mode==1' });
    expect(findInvalidConditionIds([param, channel])).toEqual(new Set());
  });

  it('condition ссылается на канал (не параметр) — невалидно', () => {
    const channel1 = createTestRegister({ name: 'Dual Speed Mode', is_parameter: false });
    const channel2 = createTestRegister({ name: 'Button Speed', condition: 'dual_speed_mode==1' });
    const result = findInvalidConditionIds([channel1, channel2]);
    expect(result).toEqual(new Set([channel2.id]));
  });

  it('condition с несколькими ссылками — одна на канал делает невалидным', () => {
    const param = createTestRegister({ name: 'Mode', is_parameter: true });
    const channel = createTestRegister({ name: 'Status', is_parameter: false });
    const dependent = createTestRegister({
      name: 'Value',
      condition: 'mode==1 && status==0',
    });
    const result = findInvalidConditionIds([param, channel, dependent]);
    expect(result).toEqual(new Set([dependent.id]));
  });

  it('condition ссылается на несуществующий регистр — не невалидно (нет target)', () => {
    const reg = createTestRegister({ name: 'Speed', condition: 'nonexistent_param==1' });
    expect(findInvalidConditionIds([reg])).toEqual(new Set());
  });

  it('condition с операторами != >= <= > <', () => {
    const channel = createTestRegister({ name: 'Temperature', is_parameter: false });
    const dep1 = createTestRegister({ name: 'Alert', condition: 'temperature>=50' });
    const dep2 = createTestRegister({ name: 'Warning', condition: 'temperature!=0' });
    const result = findInvalidConditionIds([channel, dep1, dep2]);
    expect(result).toEqual(new Set([dep1.id, dep2.id]));
  });

  it('совпадение по original_channel_id', () => {
    const channel = createTestRegister({
      name: 'My Channel',
      is_parameter: false,
      original_channel_id: 'speed_control',
    });
    const dep = createTestRegister({ name: 'Limiter', condition: 'speed_control==1' });
    const result = findInvalidConditionIds([channel, dep]);
    expect(result).toEqual(new Set([dep.id]));
  });

  it('совпадение по id регистра', () => {
    const channel = createTestRegister({
      id: 'dual_speed',
      name: 'Something Else',
      is_parameter: false,
    });
    const dep = createTestRegister({ name: 'Dep', condition: 'dual_speed==1' });
    const result = findInvalidConditionIds([channel, dep]);
    expect(result).toEqual(new Set([dep.id]));
  });

  it('несколько невалидных регистров', () => {
    const ch = createTestRegister({ name: 'WiFi', is_parameter: false });
    const dep1 = createTestRegister({ name: 'A', condition: 'wifi==1' });
    const dep2 = createTestRegister({ name: 'B', condition: 'wifi==0' });
    const result = findInvalidConditionIds([ch, dep1, dep2]);
    expect(result).toEqual(new Set([dep1.id, dep2.id]));
  });
});
