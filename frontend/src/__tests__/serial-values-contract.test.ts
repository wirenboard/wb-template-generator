import { describe, expect, it } from 'vitest';
import { compareAddresses, parseAddressInput } from '../utils/serialValues';
// Копия backend/tests/fixtures/serial_values_contract.json. Идентичность копий в двух
// деревьях сторожит test_fixture_copies_in_sync на бэкенде — он видит оба дерева
// на полном чекауте
import contract from './fixtures/serial_values_contract.json';

describe('контракт с backend/serial_values.py', () => {
  it.each(contract.parse)('разбор записи $raw', ({ raw, stored }) => {
    expect(parseAddressInput(raw)).toEqual(stored);
  });

  it('порядок сортировки общий', () => {
    const sorted = [...contract.order.unsorted].sort(compareAddresses);
    expect(sorted).toEqual(contract.order.sorted);
  });
});
