import { describe, it, expect } from 'vitest';
import { addressSortValue, numericValue, parseAddressInput } from '../utils/serialValues';

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

describe('addressSortValue', () => {
  it('считает hex по значению, а не по строке', () => {
    expect(addressSortValue('0xff')).toBe(255);
    expect(addressSortValue('0x10')).toBe(16);
  });

  it('число отдаёт как есть', () => {
    expect(addressSortValue(109)).toBe(109);
  });

  it('побитовый адрес сортирует по своему регистру', () => {
    expect(addressSortValue('109:1:2')).toBe(109);
    expect(addressSortValue('0x6D:0:1')).toBe(109);
  });

  it('неразобранный адрес не ломает сортировку', () => {
    expect(addressSortValue('12abc')).toBe(0);
    expect(addressSortValue(undefined)).toBe(0);
  });

  it('упорядочивает смешанный список по значению адреса', () => {
    const addresses: Array<string | number> = [9, '0xff', 10, 255, '0x10', 2];
    const sorted = [...addresses].sort((a, b) => addressSortValue(a) - addressSortValue(b));
    expect(sorted).toEqual([2, 9, 10, '0x10', '0xff', 255]);
  });
});

describe('numericValue', () => {
  it('разбирает hex-лимит — «max»: «0xff» есть в шаблонах wb-mqtt-serial', () => {
    expect(numericValue('0xff')).toBe(255);
    expect(numericValue('0x0A')).toBe(10);
  });

  it('принимает обе записи дробного числа', () => {
    expect(numericValue('0,5')).toBe(0.5);
    expect(numericValue('0.5')).toBe(0.5);
  });

  it('число отдаёт как есть, включая отрицательное', () => {
    expect(numericValue(100)).toBe(100);
    expect(numericValue(-99.9)).toBe(-99.9);
  });

  it('неразобранное даёт null, а не подставляет ноль', () => {
    expect(numericValue('мин')).toBeNull();
    expect(numericValue('')).toBeNull();
    expect(numericValue(undefined)).toBeNull();
  });
});
