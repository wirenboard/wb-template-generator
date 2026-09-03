import { useState, useCallback, useRef, useMemo, useEffect, Fragment } from 'react';
import { useStore } from '../store';
import type { Register } from '../types';
import { REG_TYPES, UNITS, CHANNEL_TYPES, PARAMETER_CHANNEL_TYPES, getChannelTypesForRegType, HAS_NON_LATIN } from '../constants';
import { generateId } from '../utils';
import { compareAddresses, parseAddressInput } from '../utils/serialValues';
import { nextField, deleteTargets, isTypingTarget, rowIdFromDomId, rowHotkeyAction } from '../utils/tableNavigation';
import { findInvalidConditionIds } from '../utils/conditionValidation';
import { getRegisterSeverity, type FieldValidationError } from '../utils/registerValidation';
import { translateStrings } from '../api';
import { useT, useHasTranslations, useLocale } from '../i18n';
import FormatSelect from './FormatSelect';
import RegisterDetailPanel from './RegisterDetailPanel';
import GroupManager from './GroupManager';
import LanguageManager from './LanguageManager';
import LlmImportModal from './LlmImportModal';
import { LlmSettingsModal } from './LlmSettings';

/** Props из App.tsx — файловые операции, перенесённые в тулбар */
interface RegisterTableProps {
  onDownloadJson: () => void;
  onDownloadJinja: () => void | Promise<void>;
  downloadOpen: boolean;
  setDownloadOpen: (open: boolean) => void;
  downloadRef: React.RefObject<HTMLDivElement>;
  onResetAll: () => void;
  /** Открыта модалка, которой владеет App — тогда таблица не слушает клавиши строк */
  modalOpen?: boolean;
}

/** Состояние undo-удаления */
interface UndoState {
  deletedRegisters: Register[];
  message: string;
}

/** Ключи, которые можно редактировать inline */
type EditableField =
  | 'address'
  | 'name'
  | 'reg_type'
  | 'format'
  | 'units'
  | 'channel_type'
  | 'group';

interface EditingCell {
  registerId: string;
  field: EditableField;
}

type SortField = 'enabled' | 'address' | 'name' | 'reg_type' | 'format' | 'units' | 'channel_type' | 'group' | 'is_parameter' | 'readonly';

// --- Утилиты Enum (для CSV совместимости) ---

/** Сериализация enum в строку "0:Off,1:On,2:Auto" */
function enumToString(values?: number[], titles?: string[]): string {
  if (!values || values.length === 0) return '';
  return values.map((v, i) => `${v}:${titles?.[i] ?? v}`).join(',');
}

/** Парсинг строки "0:Off,1:On" → { enum, enum_titles } */
function parseEnumString(str: string): { enum: number[]; enum_titles: string[] } | null {
  const trimmed = str.trim();
  if (!trimmed) return null;
  const parts = trimmed.split(',').map((s) => s.trim()).filter(Boolean);
  const values: number[] = [];
  const titles: string[] = [];
  for (const part of parts) {
    const colonIdx = part.indexOf(':');
    if (colonIdx === -1) {
      const num = parseInt(part, 10);
      if (isNaN(num)) continue;
      values.push(num);
      titles.push(part);
    } else {
      const num = parseInt(part.slice(0, colonIdx), 10);
      if (isNaN(num)) continue;
      values.push(num);
      titles.push(part.slice(colonIdx + 1).trim() || String(num));
    }
  }
  return values.length > 0 ? { enum: values, enum_titles: titles } : null;
}

/** Сериализация переводов enum_entries для одного языка: "0:Выкл,1:Вкл" */
function enumTranslationsToString(entries: Array<{ value: number; translations?: Record<string, string> }>, lang: string): string {
  const parts: string[] = [];
  for (const e of entries) {
    const tr = e.translations?.[lang];
    if (tr) parts.push(`${e.value}:${tr}`);
  }
  return parts.join(',');
}

/** Таблица регистров устройства */
export default function RegisterTable({
  onDownloadJson,
  onDownloadJinja,
  downloadOpen,
  setDownloadOpen,
  downloadRef,
  onResetAll,
  modalOpen,
}: RegisterTableProps) {
  const t = useT();
  const hasTranslations = useHasTranslations();
  const registers = useStore((s) => s.registers);
  const groups = useStore((s) => s.groups);
  const updateRegister = useStore((s) => s.updateRegister);
  const addRegister = useStore((s) => s.addRegister);
  const removeRegister = useStore((s) => s.removeRegister);
  const toggleRegister = useStore((s) => s.toggleRegister);
  const highlightedRegisterId = useStore((s) => s.highlightedRegisterId);
  const setHighlightedRegister = useStore((s) => s.setHighlightedRegister);
  const newlyAddedRegisterId = useStore((s) => s.newlyAddedRegisterId);
  const expandedRows = useStore((s) => s.expandedRows);
  const toggleRowExpanded = useStore((s) => s.toggleRowExpanded);
  const collapsedGroups = useStore((s) => s.collapsedGroups);
  const toggleGroupCollapsed = useStore((s) => s.toggleGroupCollapsed);
  const collapseAllGroups = useStore((s) => s.collapseAllGroups);
  const expandAllGroups = useStore((s) => s.expandAllGroups);
  const moveRegistersToGroup = useStore((s) => s.moveRegistersToGroup);
  const reorderRegister = useStore((s) => s.reorderRegister);
  const languages = useStore((s) => s.languages);
  const [uiLocale] = useLocale();
  const llmAvailable = useStore((s) => s.llmAvailable);
  const llmConfig = useStore((s) => s.llmConfig);
  const translating = useStore((s) => s.translating);
  const translateResult = useStore((s) => s.translateResult);
  const translateError = useStore((s) => s.translateError);
  const translateAll = useStore((s) => s.translateAll);
  const normalizeToEnglish = useStore((s) => s.normalizeToEnglish);
  const importTemplateAction = useStore((s) => s.importTemplate);
  const importing = useStore((s) => s.importing);
  const importError = useStore((s) => s.importError);

  // Нормализация имени: "Show modes as range" → "show_modes_as_range"
  // Условия в wb-mqtt-serial ссылаются по ключу параметра (snake_case),
  // а register.name хранит читаемое имя с пробелами
  const normalize = useCallback((name: string) =>
    name.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, ''),
  []);

  // Карта: id параметра → количество каналов, которые на него ссылаются через condition
  // Используется для постоянного бейджа «влияет на N каналов» рядом с именем параметра
  const conditionDependentsMap = useMemo(() => {
    const map = new Map<string, number>();
    // Собираем все condition-ссылки
    for (const reg of registers) {
      if (!reg.condition) continue;
      // Извлекаем все имена параметров из condition (может быть несколько через && / ||)
      // Скобки и isDefined() могут предшествовать имени, поэтому используем lookbehind-free подход
      const refs = reg.condition.matchAll(/(?:^|[^a-zA-Z0-9_])([a-zA-Z_][a-zA-Z0-9_ ]*?)(?:==|!=|>=|<=|>|<)/g);
      for (const m of refs) {
        const refNorm = normalize(m[1].trim());
        // Ищем параметр по имени, id или original_channel_id
        const param = registers.find((r) => r.is_parameter && (
          normalize(r.name) === refNorm || normalize(r.id) === refNorm ||
          (r.original_channel_id && normalize(r.original_channel_id) === refNorm)
        ));
        if (param) {
          map.set(param.id, (map.get(param.id) ?? 0) + 1);
        }
      }
    }
    return map;
  }, [registers, normalize]);

  // Набор id регистров, у которых condition ссылается на канал (не параметр) — невалидная зависимость
  const invalidConditionIds = useMemo(() => findInvalidConditionIds(registers), [registers]);

  // Валидация регистров
  const validationMap = useStore((s) => s.validationMap);
  const validationErrorCount = useStore((s) => s.validationErrorCount);
  const validationWarningCount = useStore((s) => s.validationWarningCount);
  const fixWithAi = useStore((s) => s.fixWithAi);
  const fixingWithAi = useStore((s) => s.fixingWithAi);
  const fixWithAiError = useStore((s) => s.fixWithAiError);

  // Вычисляем зависимые регистры для подсветки
  const relatedRegisterIds = useMemo(() => {
    if (!highlightedRegisterId) return new Set<string>();
    const highlighted = registers.find((r) => r.id === highlightedRegisterId);
    if (!highlighted) return new Set<string>();

    const related = new Set<string>();
    const highlightedNorm = normalize(highlighted.name);

    // Извлекает все имена параметров из condition
    const extractConditionRefs = (condition: string): string[] => {
      const refs: string[] = [];
      for (const m of condition.matchAll(
        /(?:^|[^a-zA-Z0-9_])([a-zA-Z_][a-zA-Z0-9_]*?)(?:==|!=|>=|<=|>|<)/g
      )) {
        refs.push(normalize(m[1].trim()));
      }
      return refs;
    };

    // Ищет регистр по ссылке из condition (может быть id, name или original_channel_id)
    const matchesRef = (r: typeof registers[0], ref: string) =>
      normalize(r.name) === ref || normalize(r.id) === ref ||
      (r.original_channel_id && normalize(r.original_channel_id) === ref);
    const findByCondRef = (ref: string) =>
      registers.find((r) => matchesRef(r, ref));

    // Все нормализованные идентификаторы выделенного регистра
    const highlightedRefs = [
      highlightedNorm,
      normalize(highlighted.id),
      ...(highlighted.original_channel_id ? [normalize(highlighted.original_channel_id)] : []),
    ];

    // 1. Регистры, чьи condition ссылаются на выделенный (зависят от него)
    for (const reg of registers) {
      if (reg.id === highlightedRegisterId || !reg.condition) continue;
      const refs = extractConditionRefs(reg.condition);
      if (refs.some((r) => highlightedRefs.includes(r))) {
        related.add(reg.id);
      }
    }

    // 2. Регистры, на которые ссылается condition выделенного (влияют на него)
    if (highlighted.condition) {
      const refs = extractConditionRefs(highlighted.condition);
      for (const condRef of refs) {
        const source = findByCondRef(condRef);
        if (source) related.add(source.id);
      }
    }

    return related;
  }, [highlightedRegisterId, registers, normalize]);

  // Автоскролл к выделенному регистру (только десктоп, xl+)
  useEffect(() => {
    if (!highlightedRegisterId) return;
    if (window.innerWidth < 1280) return;
    requestAnimationFrame(() => {
      const el = document.getElementById(`reg-row-${highlightedRegisterId}`);
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    });
  }, [highlightedRegisterId]);

  // Автоскролл + разворот группы при добавлении нового регистра
  useEffect(() => {
    if (!newlyAddedRegisterId) return;
    const reg = registers.find((r) => r.id === newlyAddedRegisterId);
    if (reg && collapsedGroups.has(reg.group)) {
      toggleGroupCollapsed(reg.group);
    }
    requestAnimationFrame(() => {
      const el = document.getElementById(`reg-row-${newlyAddedRegisterId}`);
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    });
  }, [newlyAddedRegisterId]); // eslint-disable-line react-hooks/exhaustive-deps

  const [editing, setEditing] = useState<EditingCell | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [sortField, setSortField] = useState<SortField | null>(null);
  const [dragOverGroupId, setDragOverGroupId] = useState<string | null>(null);
  const [dropIndicator, setDropIndicator] = useState<{ regId: string; position: 'before' | 'after' } | null>(null);
  const draggedRegIdRef = useRef<string | null>(null);
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc');
  const [groupManagerOpen, setGroupManagerOpen] = useState(false);
  const [languageManagerOpen, setLanguageManagerOpen] = useState(false);
  const [llmImportOpen, setLlmImportOpen] = useState(false);
  const [llmSettingsOpen, setLlmSettingsOpen] = useState(false);
  const [translateMenuOpen, setTranslateMenuOpen] = useState(false);
  const [openMenu, setOpenMenu] = useState<string | null>(null);
  const csvInputRef = useRef<HTMLInputElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  // Hero drop zone — приём файлов при пустой таблице (роутинг по расширению)
  const [heroDragging, setHeroDragging] = useState(false);
  const addFiles = useStore((s) => s.addFiles);
  const importTemplateStore = useStore((s) => s.importTemplate);

  // Закрываем dropdown при клике снаружи
  useEffect(() => {
    if (!openMenu) return;
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpenMenu(null);
        setTranslateMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [openMenu]);

  // Undo-удаление
  const [undoState, setUndoState] = useState<UndoState | null>(null);
  const undoTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearUndoTimer = useCallback(() => {
    if (undoTimerRef.current) {
      clearTimeout(undoTimerRef.current);
      undoTimerRef.current = null;
    }
  }, []);

  const showUndoToast = useCallback((deleted: Register[]) => {
    clearUndoTimer();
    const count = deleted.length;
    const message = count === 1
      ? t('undo.deletedOne', { name: deleted[0].name })
      : t('undo.deletedMany', { count });
    setUndoState({ deletedRegisters: deleted, message });
    undoTimerRef.current = setTimeout(() => {
      setUndoState(null);
    }, 5000);
  }, [clearUndoTimer, t]);

  const handleUndo = useCallback(() => {
    if (!undoState) return;
    clearUndoTimer();
    const currentRegisters = useStore.getState().registers;
    useStore.getState().setRegisters([...currentRegisters, ...undoState.deletedRegisters]);
    setUndoState(null);
  }, [undoState, clearUndoTimer]);

  // Ctrl+Z для отмены удаления
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'z' && undoState) {
        // Не перехватываем, когда пользователь набирает текст
        if (isTypingTarget(e.target as HTMLElement)) return;
        e.preventDefault();
        handleUndo();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [undoState, handleUndo]);

  // Очистка таймера при размонтировании
  useEffect(() => clearUndoTimer, [clearUndoTimer]);

  // Список существующих групп из регистров + из store.groups
  const groupOptions = useMemo(() => {
    const fromRegisters = new Set(registers.map((r) => r.group));
    const fromGroups = new Set(groups.map((g) => g.id));
    return Array.from(new Set([...fromGroups, ...fromRegisters])).sort();
  }, [registers, groups]);

  const sortedRegisters = useMemo(() => {
    if (!sortField) return registers;
    return [...registers].sort((a, b) => {
      const av = a[sortField];
      const bv = b[sortField];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      const cmp = sortField === 'address'
        ? compareAddresses(av as string | number, bv as string | number)
        : typeof av === 'boolean' && typeof bv === 'boolean'
          ? Number(av) - Number(bv)
          : typeof av === 'number' && typeof bv === 'number'
            ? av - bv
            : String(av).localeCompare(String(bv));
      return sortDir === 'asc' ? cmp : -cmp;
    });
  }, [registers, sortField, sortDir]);

  // Группировка регистров для отображения
  const hasMultipleGroups = useMemo(() => {
    const uniqueGroups = new Set(registers.map((r) => r.group));
    return uniqueGroups.size > 1;
  }, [registers]);

  const groupedRegisters = useMemo(() => {
    // При активной сортировке — плоский список, без группировки
    if (sortField) return null;
    // Если группа одна — не группируем
    if (!hasMultipleGroups) return null;

    // Группируем по group
    const byGroup = new Map<string, Register[]>();
    for (const reg of registers) {
      const gid = reg.group || 'general';
      if (!byGroup.has(gid)) byGroup.set(gid, []);
      byGroup.get(gid)!.push(reg);
    }

    // Сортируем группы: сначала по order из groups, потом неизвестные в конец
    const groupOrderMap = new Map<string, number>();
    for (const g of groups) {
      groupOrderMap.set(g.id, g.order);
    }

    // Строим иерархический список: top-level → подгруппы
    const topLevel = groups.filter((g) => !g.parent_group);
    const childrenOf = (parentId: string) =>
      groups.filter((g) => g.parent_group === parentId)
        .sort((a, b) => a.order - b.order);

    // Переведённый title группы: ru-перевод при ru-интерфейсе, иначе — EN title
    const localizedTitle = (g: { title: string; translations?: Record<string, { title?: string }> }): string => {
      if (uiLocale === 'ru' && g.translations?.ru?.title) return g.translations.ru.title;
      return g.title;
    };

    type GroupEntry = { id: string; title: string; registers: Register[]; level: number };
    const result: GroupEntry[] = [];

    const addGroup = (gid: string, title: string, level: number) => {
      const regs = byGroup.get(gid);
      if (regs && regs.length > 0) {
        result.push({ id: gid, title, registers: regs, level });
      }
      for (const child of childrenOf(gid)) {
        addGroup(child.id, localizedTitle(child), level + 1);
      }
    };

    // Сначала top-level группы по order
    const sortedTop = [...topLevel].sort((a, b) => a.order - b.order);
    for (const g of sortedTop) {
      addGroup(g.id, localizedTitle(g), 0);
    }

    // Группы не в дереве (не связаны ни с каким parent и не top-level)
    const addedIds = new Set(result.map((r) => r.id));
    const remaining = Array.from(byGroup.keys())
      .filter((gid) => !addedIds.has(gid))
      .sort((a, b) => {
        const oa = groupOrderMap.get(a) ?? Infinity;
        const ob = groupOrderMap.get(b) ?? Infinity;
        if (oa !== ob) return oa - ob;
        return a.localeCompare(b);
      });
    for (const gid of remaining) {
      const foundGroup = groups.find((g) => g.id === gid);
      result.push({
        id: gid,
        title: foundGroup ? localizedTitle(foundGroup) : gid,
        registers: byGroup.get(gid)!,
        level: 0,
      });
    }

    return result;
  }, [registers, groups, sortField, hasMultipleGroups, uiLocale]);

  const handleSort = useCallback((field: SortField) => {
    setSortField((prev) => {
      if (prev === field) {
        // asc → desc → сброс (null) — третий клик убирает сортировку
        if (sortDir === 'desc') {
          setSortDir('asc');
          return null;
        }
        setSortDir('desc');
        return field;
      }
      setSortDir('asc');
      return field;
    });
  }, [sortDir]);

  const startEdit = useCallback((registerId: string, field: EditableField) => {
    setEditing({ registerId, field });
  }, []);

  const stopEdit = useCallback(() => {
    setEditing(null);
  }, []);

  const handleCellChange = useCallback(
    (id: string, field: EditableField, value: string | number | boolean) => {
      if (field === 'reg_type') {
        const newRegType = String(value) as Register['reg_type'];
        const allowed = getChannelTypesForRegType(newRegType);
        const reg = registers.find((r) => r.id === id);
        if (reg && !allowed.includes(reg.channel_type)) {
          updateRegister(id, { reg_type: newRegType, channel_type: allowed[0] });
          return;
        }
        updateRegister(id, { reg_type: newRegType });
        return;
      }
      updateRegister(id, { [field]: value });
    },
    [updateRegister, registers],
  );

  const toggleSelected = useCallback((id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const deleteWithUndo = useCallback((ids: Set<string>) => {
    const deleted = registers.filter((r) => ids.has(r.id));
    if (deleted.length === 0) return;
    ids.forEach((id) => removeRegister(id));
    showUndoToast(deleted);
  }, [registers, removeRegister, showUndoToast]);

  /**
   * Единственный путь удаления — из кнопки тулбара, «x» в строке и с клавиатуры.
   * Помимо тоста отмены убирает удалённые id из отметок и снимает подсветку,
   * иначе они указывают на строки, которых больше нет.
   */
  const aliveIds = useMemo(() => new Set(registers.map((r) => r.id)), [registers]);

  /**
   * Отметки без исчезнувших строк. Локальный `selected` переживает и удаление
   * строки кнопкой «x», и сброс шаблона, и замену таблицы импортом или анализом,
   * поэтому счётчик на кнопке показывал бы строки, которых нет.
   */
  const selectedAlive = useMemo(
    () => new Set([...selected].filter((id) => aliveIds.has(id))),
    [selected, aliveIds],
  );

  const runDelete = useCallback((ids: Set<string>) => {
    deleteWithUndo(ids);
    setSelected((prev) => {
      const next = new Set([...prev].filter((id) => !ids.has(id)));
      return next.size === prev.size ? prev : next;
    });
    if (highlightedRegisterId && ids.has(highlightedRegisterId)) {
      setHighlightedRegister(null);
    }
  }, [deleteWithUndo, highlightedRegisterId, setHighlightedRegister]);

  const deleteSelected = useCallback(() => {
    runDelete(selectedAlive);
  }, [selectedAlive, runDelete]);

  // Новая строка сразу открывается на «Адресе»: вместе с переходом по Tab
  // это даёт непрерывный ввод — Insert, адрес, Tab, имя, Insert
  useEffect(() => {
    if (!newlyAddedRegisterId) return;
    setHighlightedRegister(newlyAddedRegisterId);
    startEdit(newlyAddedRegisterId, 'address');
  }, [newlyAddedRegisterId, startEdit, setHighlightedRegister]);

  // Insert — добавить регистр, Delete — удалить отмеченные или текущую строку
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      // Один источник «где фокус» на обе клавиши
      const active = (document.activeElement as HTMLElement | null) ?? (e.target as HTMLElement | null);
      const typing = active ? isTypingTarget(active) : false;
      const focusedRow = active?.closest('tr[id^="reg-row-"]') ?? null;

      const action = rowHotkeyAction({
        key: e.key,
        repeat: e.repeat,
        // Shift+Insert — вставка из буфера, Shift+Delete — вырезание
        hasModifier: e.ctrlKey || e.metaKey || e.altKey || e.shiftKey,
        // Пока открыта модалка, таблица под ней клавиши не слушает
        modalOpen: Boolean(modalOpen) || groupManagerOpen || languageManagerOpen || llmImportOpen || llmSettingsOpen,
        typing,
        inRow: focusedRow !== null,
      });
      if (!action) return;

      if (action === 'add') {
        e.preventDefault();
        // blur коммитит значение открытой ячейки, поэтому ввод не теряется
        if (typing) active?.blur();
        addRegister();
        return;
      }

      // Цель — строка, где стоит фокус: подсветка ставится только кликом мыши
      // и обходом по Tab не двигается.
      const focusedRowId = rowIdFromDomId(focusedRow?.id);
      // Подсветка — запасной вариант и только когда фокус нигде. Иначе Delete
      // сносил бы регистр, пока пользователь работает в его же панели деталей
      // (она лежит в соседнем <tr> без id) или в панели превью.
      const focusNowhere = !active || active === document.body || active === document.documentElement;
      const currentId = focusedRowId ?? (focusNowhere ? highlightedRegisterId : null);
      // Строку в свёрнутой группе не видно — удалять её молча нельзя
      const visibleId = currentId && document.getElementById(`reg-row-${currentId}`) ? currentId : null;
      const targets = deleteTargets(selectedAlive, visibleId, aliveIds);
      if (!targets) return;
      e.preventDefault();
      runDelete(targets);
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [
    addRegister, runDelete, selectedAlive, aliveIds, highlightedRegisterId,
    modalOpen, groupManagerOpen, languageManagerOpen, llmImportOpen, llmSettingsOpen,
  ]);

  // --- Скачать CSV-шаблон с примерами ---
  const downloadCsvTemplate = useCallback(() => {
    const languages = useStore.getState().languages;
    const langCodes = languages.map((l) => l.code);

    const header = [
      'enabled', 'address', 'name', 'description',
      'reg_type', 'format', 'units', 'group', 'is_parameter', 'readonly',
      'enum', ...langCodes.map((c) => `enum_${c}`),
      'condition', 'channel_type',
      ...langCodes.map((c) => `name_${c}`),
      ...langCodes.map((c) => `description_${c}`),
    ];

    // Примеры регистров
    const examples: string[][] = [
      ['1', '0', 'Voltage', 'Line voltage', 'input', 'u16', 'V', 'measurements', '0', '1', '',
        ...langCodes.map(() => ''),
        '', 'value',
        ...langCodes.map((c) => c === 'ru' ? 'Напряжение' : ''),
        ...langCodes.map((c) => c === 'ru' ? 'Напряжение сети' : ''),
      ],
      ['1', '1', 'Current', 'Line current', 'input', 'u16', 'A', 'measurements', '0', '1', '',
        ...langCodes.map(() => ''),
        '', 'value',
        ...langCodes.map((c) => c === 'ru' ? 'Ток' : ''),
        ...langCodes.map((c) => c === 'ru' ? 'Ток нагрузки' : ''),
      ],
      ['1', '2', 'Relay', 'Output relay', 'coil', 'u16', '', 'control', '0', '0', '',
        ...langCodes.map(() => ''),
        '', 'switch',
        ...langCodes.map((c) => c === 'ru' ? 'Реле' : ''),
        ...langCodes.map((c) => c === 'ru' ? 'Выходное реле' : ''),
      ],
      ['1', '10', 'Mode', 'Operating mode', 'holding', 'u16', '', 'settings', '1', '0', '"0:Off,1:Auto,2:Manual"',
        ...langCodes.map((c) => c === 'ru' ? '"0:Выкл,1:Авто,2:Ручной"' : ''),
        '', 'value',
        ...langCodes.map((c) => c === 'ru' ? 'Режим' : ''),
        ...langCodes.map((c) => c === 'ru' ? 'Режим работы' : ''),
      ],
      ['1', '20', 'Baud Rate', 'Communication speed', 'holding', 'u16', '', 'settings', '1', '0', '"0:9600,1:19200,2:115200"',
        ...langCodes.map(() => ''),
        '', 'value',
        ...langCodes.map((c) => c === 'ru' ? 'Скорость обмена' : ''),
        ...langCodes.map((c) => c === 'ru' ? 'Скорость RS-485' : ''),
      ],
    ];

    const csv = [header.join(','), ...examples.map((r) => r.join(','))].join('\n');
    const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'template_registers.csv';
    a.click();
    URL.revokeObjectURL(url);
  }, []);

  // --- CSV экспорт (RFC 4180 — запятая) ---
  const exportCsv = useCallback(() => {
    // Собираем все языки, используемые в переводах регистров
    const langSet = new Set<string>();
    for (const r of registers) {
      if (r.translations) {
        for (const lang of Object.keys(r.translations)) langSet.add(lang);
      }
    }
    // Собираем языки из enum_entries переводов
    const enumLangSet = new Set<string>();
    for (const r of registers) {
      if (r.enum_entries) {
        for (const entry of r.enum_entries) {
          if (entry.translations) {
            for (const lang of Object.keys(entry.translations)) enumLangSet.add(lang);
          }
        }
      }
    }
    const langs = Array.from(langSet).sort();
    const enumLangs = Array.from(enumLangSet).sort();

    const header = [
      'enabled', 'address', 'name', 'description',
      'reg_type', 'format', 'units', 'group', 'is_parameter', 'readonly',
      'enum', ...enumLangs.map((l) => `enum_${l}`),
      'condition', 'channel_type',
      ...langs.map((l) => `name_${l}`),
      ...langs.map((l) => `description_${l}`),
    ];
    const rows = registers.map((r) => [
      r.enabled ? '1' : '0',
      String(r.address),
      csvEscape(r.name),
      csvEscape(r.description ?? ''),
      r.reg_type,
      r.format,
      csvEscape(r.units ?? ''),
      csvEscape(r.group),
      r.is_parameter ? '1' : '0',
      r.readonly ? '1' : '0',
      csvEscape(enumToString(r.enum, r.enum_titles)),
      ...enumLangs.map((l) => csvEscape(r.enum_entries ? enumTranslationsToString(r.enum_entries, l) : '')),
      csvEscape(r.condition ?? ''),
      r.channel_type ?? 'value',
      ...langs.map((l) => csvEscape(r.translations?.[l]?.name ?? '')),
      ...langs.map((l) => csvEscape(r.translations?.[l]?.description ?? '')),
    ]);
    const csv = [header.join(','), ...rows.map((r) => r.join(','))].join('\n');
    const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'registers.csv';
    a.click();
    URL.revokeObjectURL(url);
  }, [registers]);

  // --- CSV импорт (поддержка и запятой, и точки с запятой) ---
  const importCsv = useCallback((file: File) => {
    const reader = new FileReader();
    reader.onload = (e) => {
      const text = e.target?.result as string;
      const lines = text.split('\n').filter((l) => l.trim());
      if (lines.length < 2) return;

      // Определяем разделитель по первой строке
      const headerLine = lines[0];
      const delimiter = headerLine.includes('\t') ? '\t' : headerLine.split(',').length >= headerLine.split(';').length ? ',' : ';';

      // Парсим заголовки
      const headers = parseCsvLine(headerLine, delimiter).map((h) => h.trim().toLowerCase());

      // Известные заголовки — проверяем наличие хотя бы одного ключевого
      const knownHeaders = ['enabled', 'address', 'name', 'reg_type', 'format', 'group'];
      const useHeaders = knownHeaders.some((kh) => headers.includes(kh));

      const headerMap: Record<string, number> = {};
      if (useHeaders) {
        headers.forEach((h, i) => { headerMap[h] = i; });
      }

      // Определяем колонки переводов: name_XX, description_XX
      const translationCols: { lang: string; field: 'name' | 'description'; index: number }[] = [];
      // Определяем колонки переводов enum: enum_XX
      const enumTranslationCols: { lang: string; index: number }[] = [];
      if (useHeaders) {
        headers.forEach((h, i) => {
          const nameMatch = h.match(/^name_([a-z]{2,5})$/);
          if (nameMatch) {
            translationCols.push({ lang: nameMatch[1], field: 'name', index: i });
            return;
          }
          const descMatch = h.match(/^description_([a-z]{2,5})$/);
          if (descMatch) {
            translationCols.push({ lang: descMatch[1], field: 'description', index: i });
            return;
          }
          const enumMatch = h.match(/^enum_([a-z]{2,5})$/);
          if (enumMatch) {
            enumTranslationCols.push({ lang: enumMatch[1], index: i });
          }
        });
      }

      // Автодобавление обнаруженных языков в store
      if (translationCols.length > 0 || enumTranslationCols.length > 0) {
        const store = useStore.getState();
        const existingCodes = new Set(store.languages.map((l) => l.code));
        for (const tc of translationCols) {
          if (!existingCodes.has(tc.lang) && tc.lang !== 'en') {
            store.addLanguage({ code: tc.lang, label: tc.lang });
            existingCodes.add(tc.lang);
          }
        }
        for (const ec of enumTranslationCols) {
          if (!existingCodes.has(ec.lang) && ec.lang !== 'en') {
            store.addLanguage({ code: ec.lang, label: ec.lang });
            existingCodes.add(ec.lang);
          }
        }
      }

      /** Получить значение колонки по имени заголовка или по индексу (фоллбэк) */
      const col = (cols: string[], name: string, fallbackIndex: number): string => {
        if (useHeaders) {
          const idx = headerMap[name];
          return idx !== undefined ? (cols[idx] ?? '') : '';
        }
        return cols[fallbackIndex] ?? '';
      };

      const allRegs: Register[] = [];
      for (let i = 1; i < lines.length; i++) {
        const cols = parseCsvLine(lines[i], delimiter);
        if (cols.length < 5) continue;

        const enumStr = col(cols, 'enum', 10);
        const enumParsed = enumStr ? parseEnumString(enumStr) : null;

        // Собираем переводы enum из enum_XX колонок
        const enumTranslationsByValue = new Map<number, Record<string, string>>();
        for (const ec of enumTranslationCols) {
          const enumTrStr = (cols[ec.index] ?? '').trim();
          if (enumTrStr && enumParsed) {
            const parsed = parseEnumString(enumTrStr);
            if (parsed) {
              for (let ei = 0; ei < parsed.enum.length; ei++) {
                const val = parsed.enum[ei];
                if (!enumTranslationsByValue.has(val)) enumTranslationsByValue.set(val, {});
                enumTranslationsByValue.get(val)![ec.lang] = parsed.enum_titles[ei];
              }
            }
          }
        }

        // Создаём enum_entries если есть enum + переводы
        let enumEntries: Array<{ value: number; title: string; translations?: Record<string, string> }> | undefined;
        if (enumParsed && enumTranslationsByValue.size > 0) {
          enumEntries = enumParsed.enum.map((v, ei) => {
            const tr = enumTranslationsByValue.get(v);
            return {
              value: v,
              title: enumParsed.enum_titles[ei],
              translations: tr && Object.keys(tr).length > 0 ? tr : undefined,
            };
          });
        }

        // Собираем переводы из name_XX / description_XX колонок
        const translations: Record<string, Record<string, string>> = {};
        for (const tc of translationCols) {
          const val = (cols[tc.index] ?? '').trim();
          if (val) {
            if (!translations[tc.lang]) translations[tc.lang] = {};
            translations[tc.lang][tc.field] = val;
          }
        }

        const channelType = col(cols, 'channel_type', -1) || 'value';

        allRegs.push({
          id: generateId(),
          enabled: col(cols, 'enabled', 0) !== '0',
          address: parseAddressInput(col(cols, 'address', 1)) || 0,
          name: col(cols, 'name', 2) || 'New Register',
          description: col(cols, 'description', 3) || undefined,
          reg_type: (col(cols, 'reg_type', 4) as Register['reg_type']) || 'holding',
          format: col(cols, 'format', 5) || 'u16',
          units: col(cols, 'units', 6) || undefined,
          group: col(cols, 'group', 7) || 'general',
          is_parameter: col(cols, 'is_parameter', 8) === '1',
          readonly: col(cols, 'readonly', 9) === '1',
          enum: enumParsed?.enum,
          enum_titles: enumParsed?.enum_titles,
          enum_entries: enumEntries,
          condition: col(cols, 'condition', 11) || undefined,
          scale: 1,
          offset: 0,
          access: 'read',
          channel_type: channelType as Register['channel_type'],
          translations,
        });
      }
      if (allRegs.length > 0) {
        useStore.getState().setRegisters([...useStore.getState().registers, ...allRegs]);
      }
    };
    reader.readAsText(file);
  }, []);

  // Hero drop zone — роутинг по расширению файла
  const handleHeroDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setHeroDragging(false);
    const droppedFiles = Array.from(e.dataTransfer.files);
    if (droppedFiles.length === 0) return;

    const templateFiles: File[] = [];
    const csvFiles: File[] = [];
    const docFiles: File[] = [];
    for (const f of droppedFiles) {
      const name = f.name.toLowerCase();
      if (name.endsWith('.json.jinja') || name.endsWith('.json')) {
        templateFiles.push(f);
      } else if (name.endsWith('.csv')) {
        csvFiles.push(f);
      } else {
        docFiles.push(f);
      }
    }

    if (templateFiles.length > 0) {
      importTemplateStore(templateFiles[0]);
    } else if (csvFiles.length > 0) {
      importCsv(csvFiles[0]);
    } else if (docFiles.length > 0) {
      addFiles(docFiles);
      setLlmImportOpen(true);
    }
  }, [addFiles, importTemplateStore, importCsv]);

  const sortIcon = (field: SortField) => {
    if (sortField !== field) return <span className="text-gray-300 ml-0.5">{'\u2195'}</span>;
    return <span className="text-blue-500 ml-0.5">{sortDir === 'asc' ? '\u25B2' : '\u25BC'}</span>;
  };

  const SortTh = ({ field, children, className = '' }: { field: SortField; children: React.ReactNode; className?: string }) => (
    <th
      onClick={() => handleSort(field)}
      className={`px-2 py-2 font-medium text-gray-600 cursor-pointer select-none hover:text-gray-900 ${className}`}
    >
      <span className="inline-flex items-center">
        {children}
        {sortIcon(field)}
      </span>
    </th>
  );

  const hasRegisters = registers.length > 0;

  return (
    <div>
      {hasRegisters && (
      <div className="flex flex-wrap items-center gap-2 mb-3" ref={menuRef}>
        {/* Редактирование */}
        <button onClick={addRegister} title={t('toolbar.addTip')} aria-keyshortcuts="Insert" className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 transition-colors">
          {t('toolbar.add')}
        </button>
        <span title={t('toolbar.deleteTip')}>
          <button onClick={deleteSelected} disabled={selectedAlive.size === 0} aria-keyshortcuts="Delete" className="px-3 py-1.5 text-sm bg-red-100 text-red-700 rounded hover:bg-red-200 disabled:opacity-50 disabled:cursor-not-allowed transition-colors">
            {t('toolbar.delete')} ({selectedAlive.size})
          </button>
        </span>

        {/* CSV dropdown */}
        <div className="relative">
          <button
            onClick={() => setOpenMenu(openMenu === 'csv' ? null : 'csv')}
            className="px-3 py-1.5 text-sm bg-gray-200 text-gray-700 rounded hover:bg-gray-300 transition-colors inline-flex items-center gap-1"
          >
            {t('toolbar.csv')} <span className="text-[10px]">▾</span>
          </button>
          {openMenu === 'csv' && (
            <div className="absolute z-20 mt-1 bg-white border border-gray-200 rounded-lg shadow-lg py-1 w-44 left-0">
              <button onClick={() => { exportCsv(); setOpenMenu(null); }} disabled={registers.length === 0} className="block w-full text-left px-3 py-1.5 text-sm hover:bg-gray-50 disabled:opacity-50">{t('toolbar.csvExport')}</button>
              <button onClick={() => { csvInputRef.current?.click(); setOpenMenu(null); }} className="block w-full text-left px-3 py-1.5 text-sm hover:bg-gray-50">{t('toolbar.csvImport')}</button>
              <button onClick={() => { downloadCsvTemplate(); setOpenMenu(null); }} className="block w-full text-left px-3 py-1.5 text-sm hover:bg-gray-50">{t('toolbar.csvTemplate')}</button>
            </div>
          )}
        </div>

        {/* Организация */}
        <div className="inline-flex rounded overflow-hidden">
          <button onClick={() => setGroupManagerOpen(true)} className="px-3 py-1.5 text-sm bg-gray-200 text-gray-700 rounded-l hover:bg-gray-300 transition-colors">
            {t('toolbar.groups')}
          </button>
          {hasMultipleGroups && !sortField && (() => {
            const allCollapsed = groups.every((g) => collapsedGroups.has(g.id));
            return (
              <button
                onClick={allCollapsed ? expandAllGroups : collapseAllGroups}
                className="px-1.5 py-1 bg-gray-200 text-gray-500 hover:bg-gray-300 transition-colors rounded-r border-l border-gray-300"
                title={allCollapsed ? t('misc.expandAll') : t('misc.collapseAll')}
              >
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  {allCollapsed
                    ? <path strokeLinecap="round" strokeLinejoin="round" d="M15 3h6m0 0v6m0-6l-7 7M9 21H3m0 0v-6m0 6l7-7" />
                    : <path strokeLinecap="round" strokeLinejoin="round" d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5v-4m0 4h-4m4 0l-5-5" />
                  }
                </svg>
              </button>
            );
          })()}
        </div>
        {sortField && hasMultipleGroups && (
          <button
            onClick={() => { setSortField(null); setSortDir('asc'); }}
            className="inline-flex items-center gap-1.5 px-2 py-1 text-xs bg-amber-50 text-amber-700 border border-amber-200 rounded-full hover:bg-amber-100 transition-colors"
            title={t('toolbar.sortResetTitle')}
          >
            <span>{t('toolbar.sortReset')}</span>
            <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        )}
        {hasTranslations && (
          <button onClick={() => setLanguageManagerOpen(true)} className="px-3 py-1.5 text-sm bg-gray-200 text-gray-700 rounded hover:bg-gray-300 transition-colors">
            {t('toolbar.languages')}
          </button>
        )}

        {/* AI dropdown */}
        <div className="relative">
          <button
            onClick={() => setOpenMenu(openMenu === 'ai' ? null : 'ai')}
            className="px-3 py-1.5 text-sm bg-purple-100 text-purple-700 rounded hover:bg-purple-200 transition-colors inline-flex items-center gap-1"
          >
            {t('toolbar.ai')} <span className="text-[10px]">▾</span>
          </button>
          {openMenu === 'ai' && (
            <div className="absolute z-20 mt-1 bg-white border border-gray-200 rounded-lg shadow-lg py-1 w-52 left-0">
              {/* Автоперевод — только если поддержка переводов для текущей локали */}
              {hasTranslations && (
                <div className="relative">
                  <button
                    onClick={() => setTranslateMenuOpen((v) => !v)}
                    className="block w-full text-left px-3 py-1.5 text-sm hover:bg-gray-50 flex items-center justify-between"
                    disabled={!(llmAvailable || llmConfig.apiUrl) || languages.length === 0}
                    title={!(llmAvailable || llmConfig.apiUrl) ? t('misc.llmNotConfigured') : languages.length === 0 ? t('misc.addLanguages') : t('misc.autoTranslateTitle')}
                  >
                    <span>{t('toolbar.autoTranslate')}</span>
                    <span className="text-[10px] text-gray-400">{translateMenuOpen ? '▴' : '▸'}</span>
                  </button>
                  {translateMenuOpen && (
                    <div className="border-t border-gray-100">
                      {languages.map((lang) => (
                        <button
                          key={lang.code}
                          onClick={() => { translateAll(lang.code); setTranslateMenuOpen(false); setOpenMenu(null); }}
                          disabled={translating}
                          className="block w-full text-left px-5 py-1.5 text-sm hover:bg-purple-50 disabled:opacity-50 flex items-center gap-2"
                        >
                          <span className="text-[10px] font-mono text-gray-400 uppercase w-6">{lang.code}</span>
                          <span className="truncate">{lang.label}</span>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}
              <button
                onClick={() => { normalizeToEnglish(); setOpenMenu(null); }}
                disabled={translating || !(llmAvailable || llmConfig.apiUrl)}
                className="block w-full text-left px-3 py-1.5 text-sm hover:bg-gray-50 disabled:opacity-50"
                title={t('toolbar.normalizeEnTitle')}
              >
                {t('toolbar.normalizeEn')}
              </button>
              <div className="border-t border-gray-100 my-0.5" />
              <button onClick={() => { setLlmSettingsOpen(true); setOpenMenu(null); }} className="block w-full text-left px-3 py-1.5 text-sm hover:bg-gray-50">{t('toolbar.llmSettings')}</button>
            </div>
          )}
        </div>

        {translating && (
          <span className="inline-flex items-center gap-1.5 text-xs text-purple-600">
            <svg className="w-3 h-3 animate-spin" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" strokeDasharray="31.4 31.4" /></svg>
            {t('toolbar.translating')}
          </span>
        )}
        {translateResult && !translating && (
          <span className="text-xs text-green-600">{translateResult}</span>
        )}
        {translateError && !translating && (
          <span className="text-xs text-red-600 max-w-72 whitespace-pre-wrap break-words">{translateError}</span>
        )}
        {/* Счётчик ошибок валидации + кнопка "Исправить через AI" */}
        {(validationErrorCount > 0 || validationWarningCount > 0) && (
          <span className="inline-flex items-center gap-1.5 text-xs">
            {validationErrorCount > 0 && (
              <span className="text-red-600 font-medium">{t('validation.errorCount', { count: validationErrorCount })}</span>
            )}
            {validationWarningCount > 0 && (
              <span className="text-amber-600">{t('validation.warningCount', { count: validationWarningCount })}</span>
            )}
            {validationErrorCount > 0 && (
              <button
                onClick={fixWithAi}
                disabled={fixingWithAi}
                className="ml-1 px-2 py-0.5 text-xs bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 transition-colors"
                title={t('validation.fixWithAiTip')}
              >
                {fixingWithAi ? t('validation.fixing') : t('validation.fixWithAi')}
              </button>
            )}
          </span>
        )}
        {fixWithAiError && (
          <span className="text-xs text-red-600 max-w-72 whitespace-pre-wrap break-words">{fixWithAiError}</span>
        )}

        {/* Экспорт (правая сторона) */}
        <div className="ml-auto flex items-center gap-2">
          <div className="relative" ref={downloadRef}>
            <button
              onClick={() => setDownloadOpen(!downloadOpen)}
              disabled={registers.length === 0}
              className="px-3 py-1.5 text-sm bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50 transition-colors inline-flex items-center gap-1"
            >
              {t('toolbar.download')} <span className="text-[10px]">▾</span>
            </button>
            {downloadOpen && (
              <div className="absolute z-20 mt-1 bg-white border border-gray-200 rounded-lg shadow-lg py-1 w-64 right-0">
                <button onClick={() => { onDownloadJson(); setDownloadOpen(false); }} className="block w-full text-left px-3 py-1.5 hover:bg-gray-50">
                  <span className="text-sm">{t('toolbar.downloadJson')}</span>
                  <span className="block text-[11px] text-gray-400">{t('toolbar.downloadJsonHint')}</span>
                </button>
                <button onClick={() => { onDownloadJinja(); }} className="block w-full text-left px-3 py-1.5 hover:bg-gray-50">
                  <span className="text-sm">{t('toolbar.downloadJinja')}</span>
                  <span className="block text-[11px] text-gray-400">{t('toolbar.downloadJinjaHint')}</span>
                </button>
              </div>
            )}
          </div>
          <button
            onClick={onResetAll}
            className="px-3 py-1.5 text-sm bg-gray-200 text-gray-700 rounded hover:bg-gray-300 transition-colors"
          >
            {t('toolbar.newTemplate')}
          </button>
          <span className="text-sm text-gray-500">{t('toolbar.regCount', { count: registers.length })}</span>
        </div>
      </div>
      )}

      {/* Hidden inputs — всегда доступны (для hero drop zone и меню) */}
      <input ref={csvInputRef} type="file" accept=".csv" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) importCsv(f); e.target.value = ''; }} />

      {hasRegisters ? (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="bg-gray-100 text-left text-xs">
                <th className="px-1 py-2 font-medium text-gray-600 w-7">
                  <input
                    type="checkbox"
                    checked={registers.length > 0 && selected.size === registers.length}
                    ref={(el) => { if (el) el.indeterminate = selected.size > 0 && selected.size < registers.length; }}
                    onChange={() => {
                      if (selected.size === registers.length) {
                        setSelected(new Set());
                      } else {
                        setSelected(new Set(registers.map((r) => r.id)));
                      }
                    }}
                    className="rounded"
                    title={t('table.selectAll')}
                  />
                </th>
                <SortTh field="enabled" className="w-8"><span title={t('table.enabledTip')}>{t('table.enabled')}</span></SortTh>
                <SortTh field="address" className="w-16"><span title={t('table.addressTip')}>{t('table.address')}</span></SortTh>
                <SortTh field="name"><span title={t('table.nameTip')}>{t('table.name')}</span></SortTh>
                <SortTh field="reg_type" className="w-24"><span title={t('table.regTypeTip')}>{t('table.regType')}</span></SortTh>
                <SortTh field="format" className="w-16"><span title={t('table.formatTip')}>{t('table.format')}</span></SortTh>
                <SortTh field="units" className="w-16"><span title={t('table.unitsTip')}>{t('table.units')}</span></SortTh>
                <SortTh field="channel_type" className="w-20"><span title={t('table.channelTypeTip')}>{t('table.channelType')}</span></SortTh>
                <SortTh field="group"><span title={t('table.groupTip')}>{t('table.group')}</span></SortTh>
                <SortTh field="readonly" className="w-8 text-center"><span title={t('table.readonlyTip')}>{t('table.readonly')}</span></SortTh>
                <SortTh field="is_parameter" className="w-8 text-center"><span title={t('table.isParameterTip')}>{t('table.isParameter')}</span></SortTh>
                <th className="px-1 py-2 font-medium text-gray-400 w-7 text-center"></th>
                <th className="px-1 py-2 font-medium text-gray-400 w-9 text-center"></th>
              </tr>
            </thead>
            <tbody>
              {groupedRegisters ? (
                groupedRegisters.map((group) => {
                  const isCollapsed = collapsedGroups.has(group.id);
                  return (
                    <Fragment key={group.id}>
                      <tr
                        id={`table-group-${group.id}`}
                        className={`border-b border-gray-200 cursor-pointer select-none transition-colors ${
                          dragOverGroupId === group.id
                            ? 'bg-blue-50 border-blue-300'
                            : group.level > 0 ? 'bg-gray-50/60 hover:bg-gray-100' : 'bg-gray-50 hover:bg-gray-100'
                        }`}
                        onClick={() => toggleGroupCollapsed(group.id)}
                        onDragOver={(e) => {
                          e.preventDefault();
                          e.dataTransfer.dropEffect = 'move';
                          setDragOverGroupId(group.id);
                        }}
                        onDragLeave={() => setDragOverGroupId(null)}
                        onDrop={(e) => {
                          e.preventDefault();
                          setDragOverGroupId(null);
                          const draggedId = draggedRegIdRef.current;
                          if (!draggedId) return;
                          // Если перетаскиваемый в selected — перемещаем всех выбранных, иначе только его
                          const idsToMove = selected.has(draggedId)
                            ? Array.from(selected)
                            : [draggedId];
                          // Не перемещаем если уже в этой группе
                          const needsMove = idsToMove.some(
                            (id) => registers.find((r) => r.id === id)?.group !== group.id,
                          );
                          if (needsMove) {
                            moveRegistersToGroup(idsToMove, group.id);
                          }
                          draggedRegIdRef.current = null;
                        }}
                      >
                        <td colSpan={13} className="px-2 py-1.5">
                          <div className="flex items-center gap-2" style={group.level > 0 ? { paddingLeft: `${group.level * 16}px` } : undefined}>
                            <svg
                              className={`w-3.5 h-3.5 transition-transform duration-150 ${isCollapsed ? '' : 'rotate-90'} ${group.level > 0 ? 'text-gray-400' : 'text-gray-500'}`}
                              fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
                            >
                              <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
                            </svg>
                            <span className={`text-xs ${group.level > 0 ? 'text-gray-500' : 'font-semibold text-gray-700'}`}>{group.title}</span>
                            <span className="text-[10px] text-gray-400">{group.registers.length}</span>
                            {dragOverGroupId === group.id && (
                              <span className="text-[10px] text-blue-500 font-medium ml-1">{t('row.dropHere')}</span>
                            )}
                          </div>
                        </td>
                      </tr>
                      {!isCollapsed && group.registers.map((reg) => (
                        <RegisterRow
                          key={reg.id}
                          reg={reg}
                          isHighlighted={highlightedRegisterId === reg.id}
                          isNewlyAdded={newlyAddedRegisterId === reg.id}
                          isRelated={relatedRegisterIds.has(reg.id)}
                          isSelected={selected.has(reg.id)}
                          isExpanded={expandedRows.has(reg.id)}
                          conditionDependentsCount={conditionDependentsMap.get(reg.id) ?? 0}
                          hasInvalidCondition={invalidConditionIds.has(reg.id)}
                          validationSeverity={getRegisterSeverity(validationMap, reg.id)}
                          validationErrors={validationMap.get(reg.id) ?? []}
                          editing={editing}
                          groupOptions={groupOptions}
                          draggable={!sortField}
                          dropGroupId={!sortField ? group.id : undefined}
                          dragOverGroupId={dragOverGroupId}
                          dropIndicator={dropIndicator}
                          onDragStart={() => { draggedRegIdRef.current = reg.id; }}
                          onDragEnd={() => { draggedRegIdRef.current = null; setDragOverGroupId(null); setDropIndicator(null); }}
                          onDragOverGroup={(gid) => { setDragOverGroupId(gid); setDropIndicator(null); }}
                          onDragLeaveGroup={() => setDragOverGroupId(null)}
                          onDropToGroup={(gid) => {
                            setDragOverGroupId(null);
                            setDropIndicator(null);
                            const draggedId = draggedRegIdRef.current;
                            if (!draggedId) return;
                            const idsToMove = selected.has(draggedId)
                              ? Array.from(selected)
                              : [draggedId];
                            const needsMove = idsToMove.some(
                              (id) => registers.find((r) => r.id === id)?.group !== gid,
                            );
                            if (needsMove) {
                              moveRegistersToGroup(idsToMove, gid);
                            }
                            draggedRegIdRef.current = null;
                          }}
                          onDragOverRow={(regId, position) => { setDropIndicator({ regId, position }); setDragOverGroupId(null); }}
                          onDragLeaveRow={() => setDropIndicator(null)}
                          onDropOnRow={(targetId, position) => {
                            setDropIndicator(null);
                            const draggedId = draggedRegIdRef.current;
                            if (!draggedId || draggedId === targetId) return;
                            reorderRegister(draggedId, targetId, position);
                            draggedRegIdRef.current = null;
                          }}
                          onToggle={() => toggleRegister(reg.id)}
                          onToggleSelect={() => toggleSelected(reg.id)}
                          onRemove={() => runDelete(new Set([reg.id]))}
                          onStartEdit={startEdit}
                          onStopEdit={stopEdit}
                          onChange={handleCellChange}
                          onToggleExpand={() => toggleRowExpanded(reg.id)}
                        />
                      ))}
                    </Fragment>
                  );
                })
              ) : (
                sortedRegisters.map((reg) => (
                  <RegisterRow
                    key={reg.id}
                    reg={reg}
                    isHighlighted={highlightedRegisterId === reg.id}
                    isNewlyAdded={newlyAddedRegisterId === reg.id}
                    isRelated={relatedRegisterIds.has(reg.id)}
                    isSelected={selected.has(reg.id)}
                    isExpanded={expandedRows.has(reg.id)}
                    conditionDependentsCount={conditionDependentsMap.get(reg.id) ?? 0}
                    hasInvalidCondition={invalidConditionIds.has(reg.id)}
                    validationSeverity={getRegisterSeverity(validationMap, reg.id)}
                    validationErrors={validationMap.get(reg.id) ?? []}
                    editing={editing}
                    groupOptions={groupOptions}
                    draggable={!sortField}
                    dropIndicator={dropIndicator}
                    onDragStart={() => { draggedRegIdRef.current = reg.id; }}
                    onDragEnd={() => { draggedRegIdRef.current = null; setDropIndicator(null); }}
                    onDragOverRow={(regId, position) => setDropIndicator({ regId, position })}
                    onDragLeaveRow={() => setDropIndicator(null)}
                    onDropOnRow={(targetId, position) => {
                      setDropIndicator(null);
                      const draggedId = draggedRegIdRef.current;
                      if (!draggedId || draggedId === targetId) return;
                      reorderRegister(draggedId, targetId, position);
                      draggedRegIdRef.current = null;
                    }}
                    onToggle={() => toggleRegister(reg.id)}
                    onToggleSelect={() => toggleSelected(reg.id)}
                    onRemove={() => runDelete(new Set([reg.id]))}
                    onStartEdit={startEdit}
                    onStopEdit={stopEdit}
                    onChange={handleCellChange}
                    onToggleExpand={() => toggleRowExpanded(reg.id)}
                  />
                ))
              )}
            </tbody>
          </table>
        </div>
      ) : (
        <div
          onDrop={handleHeroDrop}
          onDragOver={(e) => { e.preventDefault(); setHeroDragging(true); }}
          onDragLeave={(e) => { e.preventDefault(); if (!e.currentTarget.contains(e.relatedTarget as Node)) setHeroDragging(false); }}
          className={`rounded-xl border-2 border-dashed transition-colors py-6 ${
            heroDragging ? 'border-blue-400 bg-blue-50/40' : 'border-transparent'
          }`}
        >
          {heroDragging ? (
            <div className="flex flex-col items-center justify-center py-12 text-blue-500">
              <svg className="w-12 h-12 mb-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
              </svg>
              <p className="text-sm font-medium">{t('hero.dropHint')}</p>
            </div>
          ) : importing ? (
            <div className="flex flex-col items-center justify-center py-12 text-gray-500">
              <svg className="w-10 h-10 mb-3 animate-spin text-blue-500" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              <p className="text-sm font-medium">{t('hero.importing')}</p>
            </div>
          ) : (
            <>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                {/* Из документа (AI) — основной путь */}
                <button
                  onClick={() => setLlmImportOpen(true)}
                  className="flex flex-col items-center text-center border border-blue-200 bg-blue-50/30 rounded-xl p-6 hover:border-blue-400 hover:shadow-md transition cursor-pointer"
                >
                  <svg className="w-8 h-8 text-blue-500 mb-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 00-2.455 2.456z" />
                  </svg>
                  <h3 className="text-sm font-semibold text-gray-800 mb-1">{t('hero.aiTitle')}</h3>
                  <p className="text-xs text-gray-500 mb-3">{t('hero.aiDesc')}</p>
                  <span className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 transition-colors">{t('hero.aiButton')}</span>
                </button>

                {/* Импорт шаблона — label нативно открывает file dialog */}
                <label
                  className="flex flex-col items-center text-center border border-gray-200 rounded-xl p-6 hover:border-blue-300 hover:shadow-md transition cursor-pointer"
                >
                  <svg className="w-8 h-8 text-gray-400 mb-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
                  </svg>
                  <h3 className="text-sm font-semibold text-gray-800 mb-1">{t('hero.importTitle')}</h3>
                  <p className="text-xs text-gray-500 mb-3">{t('hero.importDesc')}</p>
                  <span className="px-3 py-1.5 text-sm bg-gray-200 text-gray-700 rounded hover:bg-gray-300 transition-colors">{t('hero.importButton')}</span>
                  <input
                    type="file"
                    accept=".json,.json.jinja"
                    onChange={(e) => { const f = e.target.files?.[0]; if (f) importTemplateAction(f); e.target.value = ''; }}
                    className="hidden"
                  />
                </label>

                {/* Вручную / CSV */}
                <button
                  onClick={addRegister}
                  className="flex flex-col items-center text-center border border-gray-200 rounded-xl p-6 hover:border-blue-300 hover:shadow-md transition cursor-pointer"
                >
                  <svg className="w-8 h-8 text-gray-400 mb-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M3.375 19.5h17.25m-17.25 0a1.125 1.125 0 01-1.125-1.125M3.375 19.5h7.5c.621 0 1.125-.504 1.125-1.125m-9.75 0V5.625m0 12.75v-1.5c0-.621.504-1.125 1.125-1.125m18.375 2.625V5.625m0 12.75c0 .621-.504 1.125-1.125 1.125m1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125m0 3.75h-7.5A1.125 1.125 0 0112 18.375m9.75-12.75c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125m19.5 0v1.5c0 .621-.504 1.125-1.125 1.125M2.25 5.625v1.5c0 .621.504 1.125 1.125 1.125m0 0h17.25m-17.25 0h7.5c.621 0 1.125.504 1.125 1.125M3.375 8.25c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125m17.25-3.75h-7.5c-.621 0-1.125.504-1.125 1.125m8.625-1.125c.621 0 1.125.504 1.125 1.125v1.5c0 .621-.504 1.125-1.125 1.125m-17.25 0h7.5m-7.5 0c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125M12 10.875v-1.5m0 1.5c0 .621-.504 1.125-1.125 1.125M12 10.875c0 .621.504 1.125 1.125 1.125m-2.25 0c.621 0 1.125.504 1.125 1.125M13.125 12h7.5m-7.5 0c-.621 0-1.125.504-1.125 1.125M20.625 12c.621 0 1.125.504 1.125 1.125v1.5c0 .621-.504 1.125-1.125 1.125m-17.25 0h7.5M12 14.625v-1.5m0 1.5c0 .621-.504 1.125-1.125 1.125M12 14.625c0 .621.504 1.125 1.125 1.125m-2.25 0c.621 0 1.125.504 1.125 1.125m0 0v1.5" />
                  </svg>
                  <h3 className="text-sm font-semibold text-gray-800 mb-1">{t('hero.manualTitle')}</h3>
                  <p className="text-xs text-gray-500 mb-3">{t('hero.manualDesc')}</p>
                  <span className="px-3 py-1.5 text-sm bg-gray-200 text-gray-700 rounded hover:bg-gray-300 transition-colors">{t('hero.manualButton')}</span>
                </button>
              </div>

              {/* Ошибка импорта — заметный блок под карточками */}
              {importError && (
                <div className="mt-4 bg-red-50 border border-red-200 rounded-lg p-3 flex items-start gap-2">
                  <svg className="w-5 h-5 text-red-500 mt-0.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
                  </svg>
                  <span className="text-sm text-red-700 flex-1">{importError}</span>
                  <button
                    onClick={() => useStore.setState({ importError: null })}
                    className="text-red-400 hover:text-red-600 text-lg leading-none shrink-0"
                  >&times;</button>
                </div>
              )}
            </>
          )}
        </div>
      )}

      <GroupManager isOpen={groupManagerOpen} onClose={() => setGroupManagerOpen(false)} />
      <LanguageManager isOpen={languageManagerOpen} onClose={() => setLanguageManagerOpen(false)} />
      <LlmImportModal isOpen={llmImportOpen} onClose={() => setLlmImportOpen(false)} />
      <LlmSettingsModal isOpen={llmSettingsOpen} onClose={() => setLlmSettingsOpen(false)} />

      {/* Toast undo-удаления */}
      {undoState && (
        <div className="fixed bottom-4 left-1/2 -translate-x-1/2 z-50 flex items-center gap-3 bg-gray-800 text-white text-sm rounded-lg shadow-lg px-4 py-2.5 animate-[slideUp_0.2s_ease-out]">
          <span>{undoState.message}</span>
          <button
            onClick={handleUndo}
            className="px-2 py-0.5 text-sm font-medium bg-blue-600 hover:bg-blue-500 rounded transition-colors"
          >
            {t('undo.button')}
          </button>
          <button
            onClick={() => { clearUndoTimer(); setUndoState(null); }}
            className="text-gray-400 hover:text-white text-xs ml-1"
          >
            ✕
          </button>
        </div>
      )}
    </div>
  );
}

// --- Конфигурация столбцов ---

interface ColumnConfig {
  field: EditableField;
  type: 'text' | 'number' | 'select' | 'format' | 'group';
  options?: readonly string[];
  placeholder?: string;
}

const COLUMNS: ColumnConfig[] = [
  { field: 'address', type: 'text' },
  { field: 'name', type: 'text' },
  { field: 'reg_type', type: 'select', options: REG_TYPES },
  { field: 'format', type: 'format' },
  { field: 'units', type: 'select', options: UNITS },
  { field: 'channel_type', type: 'select', options: CHANNEL_TYPES },
  { field: 'group', type: 'group' },
];

/** Поля в порядке колонок — он же порядок обхода по Tab */
const FIELDS: readonly EditableField[] = COLUMNS.map((c) => c.field);

function getDisplayValue(reg: Register, field: EditableField): string {
  const value = reg[field];
  if (value == null) return '';
  return String(value);
}

function getDefaultValue(reg: Register, field: EditableField): string | number {
  const value = reg[field];
  if (value == null) return '';
  return value as string | number;
}

// --- Компонент строки ---

interface RegisterRowProps {
  reg: Register;
  isHighlighted: boolean;
  isNewlyAdded: boolean;
  isRelated: boolean;
  isSelected: boolean;
  isExpanded: boolean;
  /** Количество каналов, зависящих от этого параметра через condition (0 = не используется) */
  conditionDependentsCount: number;
  /** condition ссылается на канал (не параметр) — невалидная зависимость */
  hasInvalidCondition: boolean;
  /** Уровень серьёзности ошибок валидации (null = нет ошибок) */
  validationSeverity: 'error' | 'warning' | null;
  /** Ошибки валидации для тултипа */
  validationErrors: FieldValidationError[];
  editing: EditingCell | null;
  groupOptions: string[];
  draggable?: boolean;
  /** ID группы для drop-зоны (при перетаскивании на строку) */
  dropGroupId?: string;
  dragOverGroupId?: string | null;
  /** Индикатор drop-позиции для reorder */
  dropIndicator?: { regId: string; position: 'before' | 'after' } | null;
  onDragStart?: () => void;
  onDragEnd?: () => void;
  onDragOverGroup?: (groupId: string) => void;
  onDragLeaveGroup?: () => void;
  onDropToGroup?: (groupId: string) => void;
  onDragOverRow?: (regId: string, position: 'before' | 'after') => void;
  onDropOnRow?: (regId: string, position: 'before' | 'after') => void;
  onDragLeaveRow?: () => void;
  onToggle: () => void;
  onToggleSelect: () => void;
  onRemove: () => void;
  onStartEdit: (id: string, field: EditableField) => void;
  onStopEdit: () => void;
  onChange: (id: string, field: EditableField, value: string | number | boolean) => void;
  onToggleExpand: () => void;
}

function RegisterRow({
  reg,
  isHighlighted,
  isNewlyAdded,
  isRelated,
  isSelected,
  isExpanded,
  conditionDependentsCount,
  hasInvalidCondition,
  validationSeverity,
  validationErrors,
  editing,
  groupOptions,
  draggable,
  dropGroupId,
  dragOverGroupId,
  dropIndicator,
  onDragStart,
  onDragEnd,
  onDragOverGroup,
  onDragLeaveGroup,
  onDropToGroup,
  onDragOverRow,
  onDropOnRow,
  onDragLeaveRow,
  onToggle,
  onToggleSelect,
  onRemove,
  onStartEdit,
  onStopEdit,
  onChange,
  onToggleExpand,
}: RegisterRowProps) {
  const t = useT();
  const updateRegister = useStore((s) => s.updateRegister);
  const setHighlightedRegister = useStore((s) => s.setHighlightedRegister);

  const isEditing = (field: EditableField) =>
    editing?.registerId === reg.id && editing.field === field;

  const isDropTarget = dropGroupId != null && dragOverGroupId === dropGroupId;
  const isReorderTarget = dropIndicator?.regId === reg.id;
  const reorderBefore = isReorderTarget && dropIndicator?.position === 'before';
  const reorderAfter = isReorderTarget && dropIndicator?.position === 'after';
  const rowClass = [
    'transition-colors',
    reorderBefore ? 'border-t-2 border-t-blue-500' : '',
    reorderAfter ? 'border-b-2 border-b-blue-500' : 'border-b border-gray-100',
    !reorderBefore && !reorderAfter && isDropTarget
      ? 'bg-blue-50'
      : isNewlyAdded ? 'bg-green-100 animate-pulse'
      : isHighlighted ? 'bg-yellow-100' : isRelated ? 'bg-purple-50' : 'hover:bg-blue-50',
  ].filter(Boolean).join(' ');

  const inputClass =
    'w-full border border-blue-400 rounded px-1 py-0.5 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500';

  /**
   * Переход на соседнюю ячейку строки. За краем колонок редактирование
   * закрывается, а фокус уходит на соседний чекбокс — так строка обходится
   * целиком: Адрес → … → Группа → R/O → Параметр → кнопки.
   */
  const moveEdit = (field: EditableField, dir: 1 | -1) => {
    const next = nextField(FIELDS, field, dir);
    if (next) {
      onStartEdit(reg.id, next);
    } else {
      onStopEdit();
      focusRowEdge(reg.id, dir === 1 ? 'after' : 'before');
    }
  };

  /**
   * Клавиатура открытой ячейки: Enter — коммит, Escape — отмена, Tab — переход.
   * Tab перехватываем: без этого onBlur размонтирует поле, и фокус,
   * лишившись элемента-источника, сваливается в document.body.
   */
  const handleEditKeyDown = (
    field: EditableField,
    e: React.KeyboardEvent<HTMLInputElement | HTMLSelectElement>,
  ) => {
    if (e.key === 'Enter') {
      // Только для текстового поля: у списка Enter выбирает подсвеченную опцию
      // в раскрытом дропдауне, и перехват отнял бы выбор с клавиатуры
      if (e.currentTarget.tagName === 'INPUT') e.currentTarget.blur();
    } else if (e.key === 'Escape') {
      onStopEdit();
    } else if (e.key === 'Tab') {
      e.preventDefault();
      // blur синхронно коммитит значение через onBlur и закрывает ячейку,
      // moveEdit тут же открывает соседнюю — оба setState батчатся
      e.currentTarget.blur();
      moveEdit(field, e.shiftKey ? -1 : 1);
    }
  };

  const renderColumnInput = (col: ColumnConfig): ((ref: React.RefCallback<HTMLElement>) => React.ReactNode) => {
    // Формат — используем FormatSelect
    if (col.type === 'format') {
      return (ref) => (
        <FormatSelect
          inputRef={ref}
          value={String(getDefaultValue(reg, col.field))}
          onChange={(val) => onChange(reg.id, col.field, val)}
          onKeyDown={(e) => handleEditKeyDown(col.field, e)}
          onBlur={onStopEdit}
          className={inputClass}
        />
      );
    }

    // Группа — dropdown с существующими + "новая..."
    if (col.type === 'group') {
      return (ref) => (
        <select
          ref={ref}
          defaultValue={getDefaultValue(reg, col.field)}
          onBlur={(e) => {
            if (e.target.value === '__new__') {
              const name = prompt(t('row.newGroupPrompt'));
              if (name) {
                onChange(reg.id, col.field, name.trim());
              }
            } else {
              onChange(reg.id, col.field, e.target.value);
            }
            onStopEdit();
          }}
          onChange={(e) => {
            if (e.target.value === '__new__') return;
            onChange(reg.id, col.field, e.target.value);
          }}
          onKeyDown={(e) => handleEditKeyDown(col.field, e)}
          className={inputClass}
        >
          {groupOptions.map((g) => (
            <option key={g} value={g}>{g}</option>
          ))}
          <option value="__new__">{t('row.newGroupOption')}</option>
        </select>
      );
    }

    if (col.type === 'select' && col.options) {
      const options = col.field === 'channel_type'
        ? (reg.is_parameter ? PARAMETER_CHANNEL_TYPES : getChannelTypesForRegType(reg.reg_type))
        : col.options;
      const currentValue = String(getDefaultValue(reg, col.field));
      // Если текущее значение не в списке — добавляем его в начало (помечаем как невалидное)
      const isCurrentInvalid = !(options as readonly string[]).includes(currentValue);
      const allOptions = isCurrentInvalid
        ? [currentValue, ...options]
        : options;
      return (ref) => (
        <select
          ref={ref}
          defaultValue={currentValue}
          onBlur={(e) => { onChange(reg.id, col.field, e.target.value); onStopEdit(); }}
          onChange={(e) => onChange(reg.id, col.field, e.target.value)}
          onKeyDown={(e) => handleEditKeyDown(col.field, e)}
          className={`${inputClass}${isCurrentInvalid ? ' text-red-600 ring-1 ring-red-400' : ''}`}
        >
          {allOptions.map((opt) => (
            <option key={opt} value={opt} className={opt === currentValue && isCurrentInvalid ? 'text-red-600' : ''}>
              {opt || t('row.none')}{opt === currentValue && isCurrentInvalid ? ' ⚠' : ''}
            </option>
          ))}
        </select>
      );
    }

    return (ref) => (
      <input
        ref={ref}
        type="text"
        defaultValue={getDefaultValue(reg, col.field)}
        onBlur={(e) => {
          // Адрес: число для десятичной записи, строка для hex и побитовой
          const val = col.field === 'address'
            ? parseAddressInput(e.target.value)
            : e.target.value;
          onChange(reg.id, col.field, val);
          onStopEdit();
        }}
        onKeyDown={(e) => handleEditKeyDown(col.field, e)}
        placeholder={col.field === 'address' ? t('row.addressPlaceholder') : col.placeholder}
        className={inputClass}
      />
    );
  };

  return (
    <>
      <tr
        id={`reg-row-${reg.id}`}
        className={rowClass}
        onDragStart={(e) => {
          if (!draggable) return;
          e.dataTransfer.effectAllowed = 'move';
          e.dataTransfer.setData('text/plain', reg.id);
          onDragStart?.();
        }}
        onDragEnd={() => { onDragEnd?.(); onDragLeaveRow?.(); }}
        onDragOver={(e) => {
          e.preventDefault();
          e.dataTransfer.dropEffect = 'move';
          // Reorder: определяем верхняя/нижняя половина строки
          if (onDragOverRow) {
            const rect = e.currentTarget.getBoundingClientRect();
            const midY = rect.top + rect.height / 2;
            onDragOverRow(reg.id, e.clientY < midY ? 'before' : 'after');
          } else if (dropGroupId) {
            onDragOverGroup?.(dropGroupId);
          }
        }}
        onDragLeave={() => { onDragLeaveRow?.(); onDragLeaveGroup?.(); }}
        onDrop={(e) => {
          e.preventDefault();
          if (onDropOnRow && dropIndicator) {
            onDropOnRow(reg.id, dropIndicator.position);
          } else if (dropGroupId) {
            onDropToGroup?.(dropGroupId);
          }
        }}
        onClick={() => setHighlightedRegister(isHighlighted ? null : reg.id)}
        onDoubleClick={onToggleExpand}
      >
        <td className="px-1 py-1">
          <div className="flex items-center gap-0.5">
            {draggable && (
              <span
                draggable
                className="cursor-grab active:cursor-grabbing text-gray-300 hover:text-gray-500 select-none flex-shrink-0"
                title={t('row.drag')}
              >
                <svg width="6" height="10" viewBox="0 0 6 10" fill="currentColor">
                  <circle cx="1" cy="1" r="1"/><circle cx="5" cy="1" r="1"/>
                  <circle cx="1" cy="5" r="1"/><circle cx="5" cy="5" r="1"/>
                  <circle cx="1" cy="9" r="1"/><circle cx="5" cy="9" r="1"/>
                </svg>
              </span>
            )}
            <input type="checkbox" data-cell={`${reg.id}:select`} checked={isSelected} onChange={onToggleSelect} className="rounded" />
          </div>
        </td>
        <td className="px-1 py-1">
          {!reg.is_parameter && (
            <input type="checkbox" data-cell={`${reg.id}:enabled`} checked={reg.enabled} onChange={onToggle} className="rounded" />
          )}
        </td>

        {COLUMNS.map((col) => (
          <td key={col.field} className="px-1 py-1">
            {col.field === 'name' ? (
              <div className="flex items-center gap-0.5">
                <div className="flex-1 min-w-0">
                  <EditableCell
                    isEditing={isEditing(col.field)}
                    displayValue={getDisplayValue(reg, col.field)}
                    placeholder={col.placeholder}
                    onStartEdit={() => onStartEdit(reg.id, col.field)}
                    renderInput={renderColumnInput(col)}
                  />
                </div>
                <NameNormalizeButton reg={reg} />
                {/* Бейдж: параметр влияет на каналы через condition */}
                {conditionDependentsCount > 0 && (
                  <span
                    className="flex-shrink-0 inline-flex items-center gap-0.5 px-1 py-0.5 text-[9px] font-medium bg-purple-100 text-purple-700 rounded cursor-help"
                    title={t('row.conditionBadge', { count: conditionDependentsCount })}
                  >
                    <svg className="w-2.5 h-2.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101" />
                      <path strokeLinecap="round" strokeLinejoin="round" d="M10.172 13.828a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.102 1.101" />
                    </svg>
                    {conditionDependentsCount}
                  </span>
                )}
                {/* Бейдж: ошибки валидации */}
                {validationSeverity && (
                  <span
                    className={`flex-shrink-0 inline-flex items-center px-1 py-0.5 text-[9px] font-medium rounded cursor-help ${
                      validationSeverity === 'error'
                        ? 'bg-red-100 text-red-700'
                        : 'bg-amber-100 text-amber-700'
                    }`}
                    title={validationErrors.map((e) => t(e.message_key, e.message_params)).join('\n')}
                  >
                    {validationSeverity === 'error' ? '!' : '⚠'}
                    {validationErrors.length > 1 ? ` ${validationErrors.length}` : ''}
                  </span>
                )}
                {/* Бейдж: канал/параметр имеет condition (зависит от другого параметра) */}
                {reg.condition && (
                  <span
                    className={`flex-shrink-0 inline-flex items-center px-1 py-0.5 text-[9px] font-medium rounded cursor-help ${
                      hasInvalidCondition
                        ? 'bg-red-100 text-red-700'
                        : 'bg-amber-100 text-amber-700'
                    }`}
                    title={hasInvalidCondition
                      ? t('row.invalidCondition', { cond: reg.condition })
                      : t('preview.conditionLabel', { cond: reg.condition })
                    }
                  >
                    {hasInvalidCondition ? '⚠ ?=' : '?='}
                  </span>
                )}
              </div>
            ) : (
              <EditableCell
                isEditing={isEditing(col.field)}
                displayValue={getDisplayValue(reg, col.field)}
                placeholder={col.placeholder}
                onStartEdit={() => onStartEdit(reg.id, col.field)}
                renderInput={renderColumnInput(col)}
              />
            )}
          </td>
        ))}

        {/* R/O */}
        <td className="px-1 py-1 text-center">
          <input type="checkbox" data-cell={`${reg.id}:readonly`} checked={reg.readonly ?? false} onChange={(e) => updateRegister(reg.id, { readonly: e.target.checked })} className="rounded" title={t('row.readonlyTip')} />
        </td>

        {/* Параметр */}
        <td className="px-1 py-1 text-center">
          <input type="checkbox" checked={reg.is_parameter} onChange={(e) => {
            const isParam = e.target.checked;
            const patch: Partial<Register> = { is_parameter: isParam };
            if (isParam && reg.channel_type !== 'value') {
              patch.channel_type = 'value';
            }
            updateRegister(reg.id, patch);
          }} className="rounded" title={reg.is_parameter ? t('row.parameterTip') : t('row.channelTip')} />
        </td>

        <td className="px-1 py-1">
          <button onClick={(e) => { e.stopPropagation(); onRemove(); }} className="text-red-400 hover:text-red-600 font-bold text-xs" title={t('row.deleteRegister')}>x</button>
        </td>

        {/* Раскрыть/свернуть — в самом конце строки */}
        <td className="px-1 py-1 text-center">
          <button
            onClick={onToggleExpand}
            className={`px-1.5 py-1 rounded transition-colors text-xs font-medium ${isExpanded ? 'bg-blue-100 text-blue-600' : 'text-gray-400 hover:text-blue-500 hover:bg-blue-50'}`}
            title={isExpanded ? t('row.collapse') : t('row.expand')}
          >
            <svg className={`w-4 h-4 transition-transform duration-150 ${isExpanded ? 'rotate-90' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
            </svg>
          </button>
        </td>
      </tr>

      {/* Панель деталей */}
      {isExpanded && (
        <tr>
          <td colSpan={13}>
            <RegisterDetailPanel register={reg} />
          </td>
        </tr>
      )}
    </>
  );
}

// --- Ячейка с inline-редактированием ---

/**
 * Увести фокус за пределы редактируемых колонок строки: вперёд — на чекбокс R/O,
 * назад — на «Вкл». У параметров чекбокса «Вкл» нет, там крайний слева — выбор строки.
 */
function focusRowEdge(regId: string, edge: 'before' | 'after') {
  const keys = edge === 'after'
    ? [`${regId}:readonly`]
    : [`${regId}:enabled`, `${regId}:select`];
  for (const key of keys) {
    const el = document.querySelector<HTMLElement>(`[data-cell="${key}"]`);
    if (el) {
      el.focus();
      return;
    }
  }
}

interface EditableCellProps {
  isEditing: boolean;
  displayValue: string;
  placeholder?: string;
  onStartEdit: () => void;
  renderInput: (ref: React.RefCallback<HTMLElement>) => React.ReactNode;
}

function EditableCell({ isEditing, displayValue, placeholder, onStartEdit, renderInput }: EditableCellProps) {
  const t = useT();
  const focusRef: React.RefCallback<HTMLElement> = (el) => {
    if (el) {
      el.focus();
      if ('select' in el && typeof el.select === 'function') {
        (el as HTMLInputElement).select();
      }
    }
  };

  if (isEditing) {
    // stopPropagation предотвращает всплытие клика до <tr>,
    // иначе setHighlightedRegister вызывает ре-рендер → пересоздание input → повторный select()
    return (
      <div onClick={(e) => e.stopPropagation()} onDoubleClick={(e) => e.stopPropagation()}>
        {renderInput(focusRef)}
      </div>
    );
  }

  // tabIndex обязателен: без него span выпадает из порядка табуляции,
  // и Tab уходил с чекбокса «Вкл» сразу на «R/O», минуя все колонки
  return (
    <span
      tabIndex={0}
      onClick={onStartEdit}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === 'F2') {
          e.preventDefault();
          onStartEdit();
        }
      }}
      className="cursor-pointer block truncate min-h-[1.25rem] text-xs rounded focus:outline-none focus:ring-2 focus:ring-blue-400"
      title={t('row.clickToEdit')}
    >
      {displayValue || <span className="text-gray-300">{placeholder ?? ''}</span>}
    </span>
  );
}

// --- Утилиты CSV (RFC 4180 — запятая) ---

// --- Кнопка нормализации имени →EN в строке таблицы ---


function NameNormalizeButton({ reg }: { reg: Register }) {
  const t = useT();
  const hasTranslations = useHasTranslations();
  const llmAvailable = useStore((s) => s.llmAvailable);
  const llmConfig = useStore((s) => s.llmConfig);
  const updateRegister = useStore((s) => s.updateRegister);
  const addLanguage = useStore((s) => s.addLanguage);
  const languages = useStore((s) => s.languages);
  const [loading, setLoading] = useState(false);

  if (!llmAvailable || !reg.name || !HAS_NON_LATIN.test(reg.name)) return null;

  return (
    <button
      onClick={async (e) => {
        e.stopPropagation();
        setLoading(true);
        try {
          const result = await translateStrings({ _: reg.name }, 'en', llmConfig);
          if (result._) {
            if (hasTranslations) {
              if (!languages.some((l) => l.code === 'ru')) {
                addLanguage({ code: 'ru', label: 'Русский' });
              }
              const translations = { ...(reg.translations ?? {}) };
              translations.ru = { ...(translations.ru ?? {}), name: reg.name };
              updateRegister(reg.id, { name: result._, translations });
            } else {
              updateRegister(reg.id, { name: result._ });
            }
          }
        } catch { /* игнорируем */ }
        setLoading(false);
      }}
      disabled={loading}
      className="flex-shrink-0 text-orange-400 hover:text-orange-600 disabled:opacity-50"
      title={t('row.normalizeToEn')}
    >
      {loading ? (
        <svg className="w-3 h-3 animate-spin" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" strokeDasharray="31.4 31.4" /></svg>
      ) : (
        <span className="text-[10px] font-bold">→EN</span>
      )}
    </button>
  );
}

function csvEscape(value: string): string {
  if (value.includes(',') || value.includes('"') || value.includes('\n')) {
    return '"' + value.replace(/"/g, '""') + '"';
  }
  return value;
}

function parseCsvLine(line: string, delimiter: string = ','): string[] {
  const result: string[] = [];
  let current = '';
  let inQuotes = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (inQuotes) {
      if (ch === '"') {
        if (i + 1 < line.length && line[i + 1] === '"') { current += '"'; i++; }
        else inQuotes = false;
      } else current += ch;
    } else {
      if (ch === '"') inQuotes = true;
      else if (ch === delimiter) { result.push(current); current = ''; }
      else current += ch;
    }
  }
  result.push(current);
  return result;
}
