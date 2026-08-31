import { describe, it, expect } from 'vitest';
import { formatNumberValue, parseNumberInput, resolveFieldValue } from '../utils/numberInput';

describe('parseNumberInput', () => {
  // На цифровом блоке в русской раскладке набирается запятая
  it('принимает точку и запятую как разделитель дробной части', () => {
    expect(parseNumberInput('0.5')).toBe(0.5);
    expect(parseNumberInput('0,5')).toBe(0.5);
  });

  it('разбирает значение с ещё не набранной дробной частью', () => {
    expect(parseNumberInput('0.')).toBe(0);
    expect(parseNumberInput('0,')).toBe(0);
    expect(parseNumberInput('.5')).toBe(0.5);
  });

  it('принимает отрицательные значения — scale=-1 инвертирует NC-реле', () => {
    expect(parseNumberInput('-1')).toBe(-1);
    expect(parseNumberInput('-0,5')).toBe(-0.5);
  });

  it('принимает экспоненциальную запись', () => {
    expect(parseNumberInput('1e-7')).toBe(1e-7);
  });

  // Пустое и ноль различаются, иначе значение поля не стереть
  it('пустое поле — отсутствие значения', () => {
    expect(parseNumberInput('')).toBeUndefined();
    expect(parseNumberInput('   ')).toBeUndefined();
  });

  it('незавершённый и неразобранный ввод оставляет значение как есть', () => {
    expect(parseNumberInput('-')).toBeNull();
    expect(parseNumberInput('.')).toBeNull();
    expect(parseNumberInput('1e')).toBeNull();
    expect(parseNumberInput('0.5abc')).toBeNull();
    expect(parseNumberInput('1.2.3')).toBeNull();
  });

  it('переполнение экспоненты не превращается в Infinity', () => {
    expect(parseNumberInput('1e400')).toBeNull();
  });

  describe('только целые', () => {
    it('принимает целое', () => {
      expect(parseNumberInput('-42', true)).toBe(-42);
    });

    it('дробную часть не принимает', () => {
      expect(parseNumberInput('1.5', true)).toBeNull();
      expect(parseNumberInput('1,5', true)).toBeNull();
    });
  });
});

describe('formatNumberValue', () => {
  it('выводит дробное всегда с точкой', () => {
    expect(formatNumberValue(0.5)).toBe('0.5');
  });

  it('пустой текст для отсутствующего значения', () => {
    expect(formatNumberValue(undefined)).toBe('');
    expect(formatNumberValue(null)).toBe('');
    expect(formatNumberValue(NaN)).toBe('');
  });

  it('ноль выводит, а не считает пустым', () => {
    expect(formatNumberValue(0)).toBe('0');
  });
});

describe('resolveFieldValue', () => {
  it('пустое поле даёт fallback там, где значение обязательное', () => {
    expect(resolveFieldValue(undefined, 1)).toBe(1);
    expect(resolveFieldValue(undefined, undefined)).toBeUndefined();
  });

  it('ноль отдаёт как есть, а не подменяет fallback', () => {
    expect(resolveFieldValue(0, 1)).toBe(0);
  });

  it('зажимает значение в границы — их держал прежний type="number"', () => {
    expect(resolveFieldValue(5, undefined, 0, 2)).toBe(2);
    expect(resolveFieldValue(-1, undefined, 0, 2)).toBe(0);
    expect(resolveFieldValue(1.5, undefined, 0, 2)).toBe(1.5);
  });
});
