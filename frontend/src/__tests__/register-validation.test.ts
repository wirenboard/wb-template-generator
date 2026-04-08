import { describe, it, expect } from 'vitest';
import {
  buildValidationMap,
  getFieldErrors,
  getRegisterSeverity,
  getValidationSummary,
  type RegisterValidationResult,
  type FieldValidationError,
} from '../utils/registerValidation';

// --- Хелперы ---

function makeError(field: string, severity: 'error' | 'warning' = 'error'): FieldValidationError {
  return {
    field,
    severity,
    message_key: `validation.invalid${field.charAt(0).toUpperCase() + field.slice(1)}`,
    message_params: { value: 'test' },
  };
}

function makeResult(id: string, errors: FieldValidationError[]): RegisterValidationResult {
  return { register_id: id, errors };
}

// ===================================================================
// Тесты buildValidationMap
// ===================================================================

describe('buildValidationMap', () => {
  it('возвращает пустой Map для пустого массива', () => {
    const map = buildValidationMap([]);
    expect(map.size).toBe(0);
  });

  it('пропускает регистры без ошибок', () => {
    const results = [
      makeResult('reg1', []),
      makeResult('reg2', [makeError('format')]),
    ];
    const map = buildValidationMap(results);
    expect(map.size).toBe(1);
    expect(map.has('reg1')).toBe(false);
    expect(map.has('reg2')).toBe(true);
  });

  it('корректно индексирует несколько регистров', () => {
    const results = [
      makeResult('reg1', [makeError('format'), makeError('name')]),
      makeResult('reg2', [makeError('address', 'warning')]),
    ];
    const map = buildValidationMap(results);
    expect(map.size).toBe(2);
    expect(map.get('reg1')!.length).toBe(2);
    expect(map.get('reg2')!.length).toBe(1);
  });
});

// ===================================================================
// Тесты getFieldErrors
// ===================================================================

describe('getFieldErrors', () => {
  it('возвращает пустой массив для несуществующего регистра', () => {
    const map = buildValidationMap([]);
    expect(getFieldErrors(map, 'nonexistent', 'format')).toEqual([]);
  });

  it('фильтрует по полю', () => {
    const results = [
      makeResult('reg1', [
        makeError('format'),
        makeError('name'),
        makeError('format', 'warning'),
      ]),
    ];
    const map = buildValidationMap(results);
    const formatErrors = getFieldErrors(map, 'reg1', 'format');
    expect(formatErrors.length).toBe(2);
    expect(formatErrors.every((e) => e.field === 'format')).toBe(true);
  });

  it('возвращает пустой массив для поля без ошибок', () => {
    const results = [makeResult('reg1', [makeError('format')])];
    const map = buildValidationMap(results);
    expect(getFieldErrors(map, 'reg1', 'address')).toEqual([]);
  });
});

// ===================================================================
// Тесты getRegisterSeverity
// ===================================================================

describe('getRegisterSeverity', () => {
  it('возвращает null для регистра без ошибок', () => {
    const map = buildValidationMap([]);
    expect(getRegisterSeverity(map, 'any')).toBeNull();
  });

  it('возвращает "error" если есть хотя бы один error', () => {
    const results = [
      makeResult('reg1', [makeError('format', 'warning'), makeError('name', 'error')]),
    ];
    const map = buildValidationMap(results);
    expect(getRegisterSeverity(map, 'reg1')).toBe('error');
  });

  it('возвращает "warning" если только warnings', () => {
    const results = [
      makeResult('reg1', [makeError('format', 'warning'), makeError('address', 'warning')]),
    ];
    const map = buildValidationMap(results);
    expect(getRegisterSeverity(map, 'reg1')).toBe('warning');
  });
});

// ===================================================================
// Тесты getValidationSummary
// ===================================================================

describe('getValidationSummary', () => {
  it('возвращает нули для пустого Map', () => {
    const map = buildValidationMap([]);
    expect(getValidationSummary(map)).toEqual({ errors: 0, warnings: 0 });
  });

  it('считает errors и warnings по всем регистрам', () => {
    const results = [
      makeResult('reg1', [makeError('format', 'error'), makeError('name', 'warning')]),
      makeResult('reg2', [makeError('address', 'error'), makeError('reg_type', 'error')]),
    ];
    const map = buildValidationMap(results);
    expect(getValidationSummary(map)).toEqual({ errors: 3, warnings: 1 });
  });
});
