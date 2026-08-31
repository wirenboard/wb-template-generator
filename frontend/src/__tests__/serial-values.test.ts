import { describe, it, expect } from 'vitest';
import {
  addressSortKey, compareAddresses, parseAddressInput, parseSerialIntInput,
} from '../utils/serialValues';

describe('parseAddressInput', () => {
  it('десятичную запись отдаёт числом', () => {
    expect(parseAddressInput('109')).toBe(109);
  });

  it('обрезает пробелы вокруг числа', () => {
    expect(parseAddressInput(' 12 ')).toBe(12);
  });

  // Адреса в даташитах печатают в hex, и драйвер такую запись принимает
  it('сохраняет hex-адрес строкой', () => {
    expect(parseAddressInput('0xff')).toBe('0xff');
    expect(parseAddressInput('0x012F0000')).toBe('0x012F0000');
  });

  it('приводит префикс hex к нижнему регистру — схема требует «0x»', () => {
    expect(parseAddressInput('0XFF')).toBe('0xFF');
  });

  it('оставляет побитовую запись строкой', () => {
    expect(parseAddressInput('109:1:2')).toBe('109:1:2');
    expect(parseAddressInput('0x10:0:1')).toBe('0x10:0:1');
  });

  it('не выкусывает число из неразобранной записи — её пометит валидатор', () => {
    expect(parseAddressInput('12abc')).toBe('12abc');
    expect(parseAddressInput('0x')).toBe('0x');
    expect(parseAddressInput('VOLTA()')).toBe('VOLTA()');
  });

  it('пустое поле оставляет пустым', () => {
    expect(parseAddressInput('  ')).toBe('');
  });
});

describe('addressSortKey', () => {
  it('считает hex по значению, а не по строке', () => {
    expect(addressSortKey('0xff')).toEqual([255]);
    expect(addressSortKey(109)).toEqual([109]);
  });

  it('побитовый адрес раскладывает по частям', () => {
    expect(addressSortKey('109:1:2')).toEqual([109, 1, 2]);
    expect(addressSortKey('0x6D:0:1')).toEqual([109, 0, 1]);
  });

  it('неразобранный адрес не ломает сортировку', () => {
    expect(addressSortKey('12abc')).toEqual([0]);
    expect(addressSortKey(undefined)).toEqual([0]);
  });

  it('упорядочивает смешанный список по значению адреса', () => {
    const addresses: Array<string | number> = [9, '0xff', 10, 255, '0x10', 2];
    expect([...addresses].sort(compareAddresses)).toEqual([2, 9, 10, '0x10', '0xff', 255]);
  });
});

describe('parseSerialIntInput', () => {
  it('оставляет hex записью — драйвер её принимает, а у somfy это код команды', () => {
    expect(parseSerialIntInput('0x0A0404')).toBe('0x0A0404');
    expect(parseSerialIntInput('0XFF')).toBe('0xFF');
  });

  it('десятичное даёт число, включая отрицательное', () => {
    expect(parseSerialIntInput('255')).toBe(255);
    expect(parseSerialIntInput('-1')).toBe(-1);
  });

  it('пустое поле стирает значение, незавершённый ввод его не трогает', () => {
    expect(parseSerialIntInput('  ')).toBeUndefined();
    expect(parseSerialIntInput('0x')).toBeNull();
    expect(parseSerialIntInput('1.5')).toBeNull();
  });
});

describe('compareAddresses', () => {
  it('упорядочивает биты одного регистра, а не считает их равными', () => {
    const bits = ['109:0:2', '109:1:1', '109:0:1'];
    expect([...bits].sort(compareAddresses)).toEqual(['109:0:1', '109:0:2', '109:1:1']);
  });

  it('сравнивает hex и десятичные по значению', () => {
    expect([9, '0xff', 10, 2].sort(compareAddresses)).toEqual([2, 9, 10, '0xff']);
  });
});

describe('разбор совпадает с серверным', () => {
  it('обрезает пробелы так же, как parse_address', () => {
    expect(parseAddressInput(' 12abc ')).toBe('12abc');
  });
});
