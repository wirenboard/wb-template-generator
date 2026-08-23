import { describe, it, expect } from 'vitest';
import {
  intakeFiles, splitByCount, splitByExtension, splitByRequestBudget, REQUEST_OVERHEAD_BYTES,
} from '../utils/uploadLimits';

const MB = 1024 * 1024;

/** Файл заданного размера — содержимое не важно, проверяется только `size` */
function fileOf(name: string, bytes: number): File {
  return new File([new Uint8Array(bytes)], name);
}

describe('splitByRequestBudget', () => {
  it('пропускает набор, помещающийся в бюджет', () => {
    const incoming = [fileOf('a.pdf', 400 * 1024), fileOf('b.pdf', 400 * 1024)];
    const { accepted, rejected } = splitByRequestBudget([], incoming, 2 * MB);
    expect(accepted).toHaveLength(2);
    expect(rejected).toHaveLength(0);
  });

  it('считает уже выбранные файлы занятым бюджетом', () => {
    const chosen = [fileOf('chosen.pdf', 1.5 * MB)];
    const { accepted, rejected } = splitByRequestBudget(chosen, [fileOf('next.pdf', MB)], 2 * MB);
    expect(accepted).toHaveLength(0);
    expect(rejected.map((f) => f.name)).toEqual(['next.pdf']);
  });

  it('отклоняет только не влезшие файлы, остальные добавляет', () => {
    const incoming = [
      fileOf('small.pdf', 100 * 1024),
      fileOf('huge.pdf', 3 * MB),
      fileOf('tail.pdf', 100 * 1024),
    ];
    const { accepted, rejected } = splitByRequestBudget([], incoming, 2 * MB);
    expect(accepted.map((f) => f.name)).toEqual(['small.pdf', 'tail.pdf']);
    expect(rejected.map((f) => f.name)).toEqual(['huge.pdf']);
  });

  // Без запаса набор ровно по лимиту доезжал бы до 413 уже после отправки
  it('оставляет запас на обвязку запроса', () => {
    const { accepted, rejected } = splitByRequestBudget([], [fileOf('exact.pdf', 2 * MB)], 2 * MB);
    expect(accepted).toHaveLength(0);
    expect(rejected).toHaveLength(1);

    const fits = fileOf('fits.pdf', 2 * MB - REQUEST_OVERHEAD_BYTES);
    expect(splitByRequestBudget([], [fits], 2 * MB).accepted).toHaveLength(1);
  });
});

const ALLOWED = ['.pdf', '.xlsx', '.png', '.jpg', '.jpeg', '.webp'];

describe('splitByExtension', () => {
  it('отклоняет расширение не из списка сервера', () => {
    const incoming = [fileOf('map.pdf', 10), fileOf('table.xls', 10), fileOf('notes.txt', 10)];
    const { accepted, rejected } = splitByExtension(incoming, ALLOWED);
    expect(accepted.map((f) => f.name)).toEqual(['map.pdf']);
    expect(rejected.map((f) => f.name)).toEqual(['table.xls', 'notes.txt']);
  });

  it('расширение сверяется без учёта регистра', () => {
    const { accepted } = splitByExtension([fileOf('SCAN.PNG', 10)], ALLOWED);
    expect(accepted).toHaveLength(1);
  });

  it('файл без расширения не проходит', () => {
    const { rejected } = splitByExtension([fileOf('datasheet', 10)], ALLOWED);
    expect(rejected).toHaveLength(1);
  });
});

describe('splitByCount', () => {
  it('считает уже выбранные файлы занятыми местами', () => {
    const chosen = [fileOf('a.pdf', 10), fileOf('b.pdf', 10)];
    const incoming = [fileOf('c.pdf', 10), fileOf('d.pdf', 10)];
    const { accepted, rejected } = splitByCount(chosen, incoming, 3);
    expect(accepted.map((f) => f.name)).toEqual(['c.pdf']);
    expect(rejected.map((f) => f.name)).toEqual(['d.pdf']);
  });

  it('на заполненном наборе не пропускает ничего', () => {
    const chosen = [fileOf('a.pdf', 10), fileOf('b.pdf', 10)];
    const { accepted, rejected } = splitByCount(chosen, [fileOf('c.pdf', 10)], 2);
    expect(accepted).toHaveLength(0);
    expect(rejected).toHaveLength(1);
  });
});

describe('intakeFiles', () => {
  const limits = { allowedExtensions: ALLOWED, maxFiles: 3, maxFileSizeMb: 2 };

  it('пропускает подходящий набор без ошибок', () => {
    const { accepted, errors } = intakeFiles([], [fileOf('map.pdf', 10)], limits);
    expect(accepted.map((f) => f.name)).toEqual(['map.pdf']);
    expect(errors).toEqual([]);
  });

  it('собирает отказы всех трёх потолков сразу', () => {
    const incoming = [
      fileOf('notes.txt', 10), fileOf('huge.pdf', 3 * MB),
      fileOf('a.pdf', 10), fileOf('b.pdf', 10), fileOf('c.pdf', 10), fileOf('d.pdf', 10),
    ];
    const { accepted, errors } = intakeFiles([], incoming, limits);
    expect(errors.map((e) => e.key)).toEqual([
      'upload.formatError', 'upload.countError', 'upload.sizeError',
    ]);
    expect(accepted.map((f) => f.name)).toEqual(['a.pdf', 'b.pdf']);
  });

  it('без потолков сервера ничего не отсекает', () => {
    const incoming = [fileOf('notes.txt', 10 * MB), fileOf('x.docx', 10)];
    const { accepted, errors } = intakeFiles(
      [], incoming, { allowedExtensions: null, maxFiles: null, maxFileSizeMb: null },
    );
    expect(accepted).toHaveLength(2);
    expect(errors).toEqual([]);
  });

  it('отказ несёт имена и параметры для подстановки', () => {
    const { errors } = intakeFiles([], [fileOf('notes.txt', 10)], limits);
    expect(errors[0].params.names).toBe('notes.txt');
    expect(errors[0].params.formats).toBe(ALLOWED.join(', '));
  });
});
