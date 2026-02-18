import { create } from 'zustand';
import type { Register, RegisterGroup, DeviceInfo, WBTemplate, AnalyzeProgress, Language } from './types';
import { buildTemplate, analyzeFiles, fetchStatus, translateStrings, importTemplate as importTemplateApi } from './api';
import { DEFAULT_LANGUAGES, LANGUAGES_STORAGE_KEY } from './constants';
import { generateId } from './utils';

// Debounce-хелпер
let buildTimeout: ReturnType<typeof setTimeout> | null = null;

// Ключи localStorage
const STATE_STORAGE_KEY = 'wb-template-state';
const CUSTOM_PROMPT_STORAGE_KEY = 'wb-template-custom-prompt';

// Загрузка языков из localStorage
function loadLanguages(): Language[] {
  try {
    const stored = localStorage.getItem(LANGUAGES_STORAGE_KEY);
    if (stored) return JSON.parse(stored);
  } catch { /* игнорируем */ }
  return [...DEFAULT_LANGUAGES];
}

function saveLanguages(langs: Language[]) {
  try {
    localStorage.setItem(LANGUAGES_STORAGE_KEY, JSON.stringify(langs));
  } catch { /* игнорируем */ }
}

// Загрузка/сохранение состояния редактора
interface SavedState {
  registers: Register[];
  groups: RegisterGroup[];
  deviceInfo: DeviceInfo;
  llmConfig: { apiUrl?: string; apiKey?: string; model?: string; maxTokens?: number; timeout?: number; legacyMaxTokens?: boolean; temperature?: number };
}

function loadState(): Partial<SavedState> {
  try {
    const stored = localStorage.getItem(STATE_STORAGE_KEY);
    if (stored) return JSON.parse(stored);
  } catch { /* игнорируем */ }
  return {};
}

function saveState(state: SavedState) {
  try {
    localStorage.setItem(STATE_STORAGE_KEY, JSON.stringify(state));
  } catch { /* игнорируем */ }
}

let saveTimeout: ReturnType<typeof setTimeout> | null = null;
function debouncedSaveState(state: SavedState) {
  if (saveTimeout) clearTimeout(saveTimeout);
  saveTimeout = setTimeout(() => saveState(state), 500);
}

interface TemplateStore {
  files: File[];
  registers: Register[];
  groups: RegisterGroup[];
  deviceInfo: DeviceInfo;
  templateType: 'small' | 'medium' | 'full';
  template: WBTemplate | null;

  analyzeStatus: 'idle' | 'loading' | 'error';
  analyzeProgress: AnalyzeProgress | null;
  analyzeError: string | null;
  analyzeRequestId: string | null;
  analyzeLog: string[];
  analyzeAbortController: AbortController | null;

  buildError: string | null;
  highlightedRegisterId: string | null;
  lastActiveGroup: string;
  newlyAddedRegisterId: string | null;
  expandedRows: Set<string>;
  llmConfig: { apiUrl?: string; apiKey?: string; model?: string; maxTokens?: number; timeout?: number; legacyMaxTokens?: boolean; temperature?: number };
  llmAvailable: boolean | null;
  serverModel: string | null;
  maxFileSizeMb: number;
  appVersion: string | null;
  previewLang: string;

  // Действия
  setFiles: (files: File[]) => void;
  addFiles: (files: File[]) => void;
  removeFile: (index: number) => void;
  setRegisters: (registers: Register[]) => void;
  updateRegister: (id: string, patch: Partial<Register>) => void;
  addRegister: () => void;
  removeRegister: (id: string) => void;
  toggleRegister: (id: string) => void;
  setDeviceInfo: (info: Partial<DeviceInfo>) => void;
  setTemplateType: (type: 'small' | 'medium' | 'full') => void;
  setTemplate: (template: WBTemplate | null) => void;
  setAnalyzeStatus: (status: 'idle' | 'loading' | 'error') => void;
  setAnalyzeProgress: (progress: AnalyzeProgress | null) => void;
  setAnalyzeError: (error: string | null) => void;
  setAnalyzeAbortController: (controller: AbortController | null) => void;
  setHighlightedRegister: (id: string | null) => void;
  clearNewlyAdded: () => void;
  setLlmConfig: (config: Partial<{ apiUrl?: string; apiKey?: string; model?: string; maxTokens?: number; timeout?: number; legacyMaxTokens?: boolean; temperature?: number }>) => void;
  setPreviewLang: (lang: string) => void;
  triggerBuild: () => void;
  cancelAnalyze: () => void;
  startAnalyze: () => void;
  checkLlmStatus: () => void;

  // Группы
  setGroups: (groups: RegisterGroup[]) => void;
  addGroup: (group: RegisterGroup) => void;
  updateGroup: (id: string, patch: Partial<RegisterGroup>) => void;
  removeGroup: (id: string) => void;

  // Языки
  languages: Language[];
  addLanguage: (lang: Language) => void;
  removeLanguage: (code: string) => void;
  setLanguages: (langs: Language[]) => void;

  // Авто-распространение enum переводов
  propagateEnumTranslation: (englishTitle: string, lang: string, translation: string) => void;

  // Автоперевод
  translating: boolean;
  translateError: string | null;
  translateResult: string | null;
  translateAll: (targetLang: string) => Promise<void>;
  normalizeToEnglish: () => Promise<void>;

  // Импорт шаблона
  importTemplate: (file: File) => Promise<void>;
  importing: boolean;
  importError: string | null;

  // Перемещение регистров между группами (DnD)
  moveRegistersToGroup: (regIds: string[], targetGroupId: string) => void;

  // Перетаскивание для изменения порядка
  reorderRegister: (draggedId: string, targetId: string, position: 'before' | 'after') => void;

  // Кастомный системный промпт
  customSystemPrompt: string | null;
  setCustomSystemPrompt: (prompt: string | null) => void;

  // Сброс всего состояния
  resetAll: () => void;

  // Раскрытие строк
  toggleRowExpanded: (id: string) => void;
  setRowExpanded: (id: string, expanded: boolean) => void;

  // Сворачивание групп в таблице
  collapsedGroups: Set<string>;
  toggleGroupCollapsed: (groupId: string) => void;
  collapseAllGroups: () => void;
  expandAllGroups: () => void;
}

// Загружаем сохранённое состояние при инициализации
const _saved = loadState();

/** Вызывает triggerBuild и сохраняет состояние в localStorage с debounce */
function buildAndSave(get: () => TemplateStore) {
  get().triggerBuild();
  const s = get();
  debouncedSaveState({ registers: s.registers, groups: s.groups, deviceInfo: s.deviceInfo, llmConfig: s.llmConfig });
}

export const useStore = create<TemplateStore>((set, get) => ({
  files: [],
  registers: _saved.registers ?? [],
  groups: _saved.groups ?? [],
  deviceInfo: _saved.deviceInfo ?? { name: '', id: '' },
  templateType: 'medium',
  template: null,

  analyzeStatus: 'idle',
  analyzeProgress: null,
  analyzeError: null,
  analyzeRequestId: null,
  analyzeLog: [],
  analyzeAbortController: null,

  buildError: null,
  highlightedRegisterId: null,
  lastActiveGroup: 'general',
  newlyAddedRegisterId: null,
  expandedRows: new Set(),
  llmConfig: _saved.llmConfig ?? {},
  llmAvailable: null,
  serverModel: null,
  maxFileSizeMb: 1,
  appVersion: null,
  previewLang: 'en',
  languages: loadLanguages(),
  collapsedGroups: new Set(),
  importing: false,
  importError: null,
  customSystemPrompt: (() => {
    try {
      return localStorage.getItem(CUSTOM_PROMPT_STORAGE_KEY);
    } catch { return null; }
  })(),
  translating: false,
  translateError: null,
  translateResult: null,

  setFiles: (files) => set({ files }),
  addFiles: (newFiles) => set((s) => ({ files: [...s.files, ...newFiles] })),
  removeFile: (index) => set((s) => ({ files: s.files.filter((_, i) => i !== index) })),

  setRegisters: (registers) => {
    set({ registers });
    buildAndSave(get);
  },

  updateRegister: (id, patch) => {
    set((s) => ({
      registers: s.registers.map((r) => (r.id === id ? { ...r, ...patch } : r)),
    }));
    buildAndSave(get);
  },

  addRegister: () => {
    const { lastActiveGroup } = get();
    const newId = generateId();
    const newReg: Register = {
      id: newId,
      address: 0,
      name: 'New Register',
      reg_type: 'holding',
      format: 'u16',
      scale: 1,
      offset: 0,
      access: 'read',
      channel_type: 'value',
      group: lastActiveGroup,
      is_parameter: false,
      enabled: true,
      translations: {},
    };
    set((s) => ({ registers: [...s.registers, newReg], newlyAddedRegisterId: newId }));
    // Убираем подсветку через 2 секунды
    setTimeout(() => {
      if (get().newlyAddedRegisterId === newId) {
        set({ newlyAddedRegisterId: null });
      }
    }, 2000);
    buildAndSave(get);
  },

  removeRegister: (id) => {
    set((s) => ({ registers: s.registers.filter((r) => r.id !== id) }));
    buildAndSave(get);
  },

  toggleRegister: (id) => {
    set((s) => ({
      registers: s.registers.map((r) =>
        r.id === id ? { ...r, enabled: !r.enabled } : r
      ),
    }));
    buildAndSave(get);
  },

  setDeviceInfo: (info) => {
    set((s) => ({ deviceInfo: { ...s.deviceInfo, ...info } }));
    buildAndSave(get);
  },
  setTemplateType: (templateType) => set({ templateType }),
  setTemplate: (template) => set({ template }),
  setAnalyzeStatus: (analyzeStatus) => set({ analyzeStatus }),
  setAnalyzeProgress: (analyzeProgress) => set({ analyzeProgress }),
  setAnalyzeError: (analyzeError) => set({ analyzeError }),
  setAnalyzeAbortController: (analyzeAbortController) => set({ analyzeAbortController }),
  setHighlightedRegister: (highlightedRegisterId) => {
    set({ highlightedRegisterId });
    if (highlightedRegisterId) {
      const reg = get().registers.find((r) => r.id === highlightedRegisterId);
      if (reg) set({ lastActiveGroup: reg.group });
    }
  },
  clearNewlyAdded: () => set({ newlyAddedRegisterId: null }),
  setLlmConfig: (config) => {
    set((s) => ({ llmConfig: { ...s.llmConfig, ...config } }));
    const s = get();
    debouncedSaveState({ registers: s.registers, groups: s.groups, deviceInfo: s.deviceInfo, llmConfig: s.llmConfig });
    get().checkLlmStatus();
  },
  setPreviewLang: (previewLang) => set({ previewLang }),

  // Группы
  setGroups: (groups) => {
    set({ groups });
    buildAndSave(get);
  },

  addGroup: (group) => {
    set((s) => ({ groups: [...s.groups, group] }));
    buildAndSave(get);
  },

  updateGroup: (id, patch) => {
    set((s) => ({
      groups: s.groups.map((g) => (g.id === id ? { ...g, ...patch } : g)),
    }));
    buildAndSave(get);
  },

  removeGroup: (id) => {
    set((s) => ({ groups: s.groups.filter((g) => g.id !== id) }));
    buildAndSave(get);
  },

  // Языки
  addLanguage: (lang) => {
    set((s) => {
      if (s.languages.some((l) => l.code === lang.code)) return s;
      const next = [...s.languages, lang];
      saveLanguages(next);
      return { languages: next };
    });
  },

  removeLanguage: (code) => {
    set((s) => {
      const next = s.languages.filter((l) => l.code !== code);
      saveLanguages(next);
      return { languages: next };
    });
  },

  setLanguages: (langs) => {
    saveLanguages(langs);
    set({ languages: langs });
  },

  // Раскрытие строк
  toggleRowExpanded: (id) => {
    set((s) => {
      const next = new Set(s.expandedRows);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return { expandedRows: next };
    });
  },

  setRowExpanded: (id, expanded) => {
    set((s) => {
      const next = new Set(s.expandedRows);
      if (expanded) next.add(id);
      else next.delete(id);
      return { expandedRows: next };
    });
  },

  // Сворачивание групп
  toggleGroupCollapsed: (groupId) => {
    set((s) => {
      const next = new Set(s.collapsedGroups);
      if (next.has(groupId)) next.delete(groupId);
      else next.add(groupId);
      return { collapsedGroups: next };
    });
  },

  collapseAllGroups: () => {
    const allGroupIds = get().groups.map((g) => g.id);
    // Также собираем группы из регистров, которых нет в groups
    const fromRegisters = new Set(get().registers.map((r) => r.group));
    for (const gid of fromRegisters) allGroupIds.push(gid);
    set({ collapsedGroups: new Set(allGroupIds) });
  },

  expandAllGroups: () => {
    set({ collapsedGroups: new Set() });
  },

  translateAll: async (targetLang) => {
    const { registers, groups, llmConfig } = get();
    // Собираем все уникальные переводимые строки без перевода на targetLang
    const strings: Record<string, string> = {};

    for (const reg of registers) {
      if (!reg.enabled) continue;
      // Имя регистра
      if (!reg.translations?.[targetLang]?.name) {
        strings[`reg_name_${reg.id}`] = reg.name;
      }
      // Описание (только для параметров)
      if (reg.description && reg.is_parameter && !reg.translations?.[targetLang]?.description) {
        strings[`reg_desc_${reg.id}`] = reg.description;
      }
      // Enum titles
      if (reg.enum_entries) {
        for (const entry of reg.enum_entries) {
          if (!entry.translations?.[targetLang]) {
            strings[`enum_${entry.title}`] = entry.title;
          }
        }
      }
    }
    // Группы
    for (const group of groups) {
      if (!group.translations?.[targetLang]?.title) {
        strings[`group_title_${group.id}`] = group.title;
      }
      if (group.description && !group.translations?.[targetLang]?.description) {
        strings[`group_desc_${group.id}`] = group.description;
      }
    }

    const totalStrings = Object.keys(strings).length;
    if (totalStrings === 0) {
      set({ translateResult: 'Все строки уже переведены', translateError: null });
      setTimeout(() => set({ translateResult: null }), 3000);
      return;
    }

    set({ translating: true, translateError: null, translateResult: null });
    try {
      const result = await translateStrings(strings, targetLang, llmConfig);
      const translated = Object.keys(result).length;

      // Распределяем результаты обратно
      set((s) => {
        const updatedRegisters = s.registers.map((reg) => {
          let changed = false;
          let translations = { ...(reg.translations ?? {}) };
          const langTr = { ...(translations[targetLang] ?? {}) };

          // Имя
          const nameKey = `reg_name_${reg.id}`;
          if (result[nameKey] && !langTr.name) {
            langTr.name = result[nameKey];
            changed = true;
          }

          // Описание
          const descKey = `reg_desc_${reg.id}`;
          if (result[descKey] && !langTr.description) {
            langTr.description = result[descKey];
            changed = true;
          }

          if (changed) {
            translations = { ...translations, [targetLang]: langTr };
          }

          // Enum entries
          let newEntries = reg.enum_entries;
          if (reg.enum_entries) {
            const updatedEntries = reg.enum_entries.map((entry) => {
              const enumKey = `enum_${entry.title}`;
              if (result[enumKey] && !entry.translations?.[targetLang]) {
                const tr = { ...(entry.translations ?? {}), [targetLang]: result[enumKey] };
                return { ...entry, translations: tr };
              }
              return entry;
            });
            if (updatedEntries.some((e, i) => e !== reg.enum_entries![i])) {
              newEntries = updatedEntries;
              changed = true;
            }
          }

          if (!changed) return reg;
          return { ...reg, translations, enum_entries: newEntries };
        });

        const updatedGroups = s.groups.map((group) => {
          let changed = false;
          const translations = { ...(group.translations ?? {}) };
          const langTr = { ...(translations[targetLang] ?? {}) };

          const titleKey = `group_title_${group.id}`;
          if (result[titleKey] && !langTr.title) {
            langTr.title = result[titleKey];
            changed = true;
          }

          const descKey = `group_desc_${group.id}`;
          if (result[descKey] && !langTr.description) {
            langTr.description = result[descKey];
            changed = true;
          }

          if (!changed) return group;
          return { ...group, translations: { ...translations, [targetLang]: langTr } };
        });

        return { registers: updatedRegisters, groups: updatedGroups };
      });
      buildAndSave(get);
      set({ translateResult: `Переведено: ${translated} из ${totalStrings}` });
      setTimeout(() => set({ translateResult: null }), 4000);
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Ошибка перевода';
      set({ translateError: msg });
    } finally {
      set({ translating: false });
    }
  },

  normalizeToEnglish: async () => {
    const hasCyrillic = (s: string) => /[а-яёА-ЯЁ]/.test(s);
    const { registers, groups, llmConfig } = get();

    // Собираем строки с кириллицей для перевода на EN
    const strings: Record<string, string> = {};
    // Запоминаем какие поля откуда взяты (для обратной записи)
    const regNameKeys: string[] = [];
    const regDescKeys: string[] = [];
    const groupTitleKeys: string[] = [];
    const groupDescKeys: string[] = [];
    const enumKeys: string[] = [];

    for (const reg of registers) {
      if (!reg.enabled) continue;
      if (hasCyrillic(reg.name)) {
        const key = `reg_name_${reg.id}`;
        strings[key] = reg.name;
        regNameKeys.push(key);
      }
      if (reg.description && hasCyrillic(reg.description)) {
        const key = `reg_desc_${reg.id}`;
        strings[key] = reg.description;
        regDescKeys.push(key);
      }
      // Enum titles с кириллицей
      if (reg.enum_entries) {
        for (const entry of reg.enum_entries) {
          if (hasCyrillic(entry.title)) {
            const key = `enum_${reg.id}_${entry.value}`;
            strings[key] = entry.title;
            enumKeys.push(key);
          }
        }
      }
    }
    for (const group of groups) {
      if (hasCyrillic(group.title)) {
        const key = `group_title_${group.id}`;
        strings[key] = group.title;
        groupTitleKeys.push(key);
      }
      if (group.description && hasCyrillic(group.description)) {
        const key = `group_desc_${group.id}`;
        strings[key] = group.description;
        groupDescKeys.push(key);
      }
    }

    const totalStrings = Object.keys(strings).length;
    if (totalStrings === 0) {
      set({ translateResult: 'Нет строк с кириллицей для перевода', translateError: null });
      setTimeout(() => set({ translateResult: null }), 3000);
      return;
    }

    set({ translating: true, translateError: null, translateResult: null });
    try {
      const result = await translateStrings(strings, 'en', llmConfig);
      const translated = Object.keys(result).length;

      // Обеспечиваем наличие языка 'ru' в store
      const store = useStore.getState();
      if (!store.languages.some((l) => l.code === 'ru')) {
        store.addLanguage({ code: 'ru', label: 'Русский' });
      }

      set((s) => {
        const updatedRegisters = s.registers.map((reg) => {
          const nameKey = `reg_name_${reg.id}`;
          const descKey = `reg_desc_${reg.id}`;
          const hasNewName = regNameKeys.includes(nameKey) && result[nameKey];
          const hasNewDesc = regDescKeys.includes(descKey) && result[descKey];

          if (!hasNewName && !hasNewDesc && !reg.enum_entries) return reg;

          let translations = { ...(reg.translations ?? {}) };
          const ruTr = { ...(translations.ru ?? {}) };
          let newName = reg.name;
          let newDescription = reg.description;

          // Сохраняем русский в translations.ru, заменяем на английский
          if (hasNewName) {
            ruTr.name = reg.name;
            newName = result[nameKey];
          }
          if (hasNewDesc) {
            ruTr.description = reg.description!;
            newDescription = result[descKey];
          }
          translations = { ...translations, ru: ruTr };

          // Enum: сохраняем русский в translations, заменяем title на английский
          let newEntries = reg.enum_entries;
          if (reg.enum_entries) {
            let changed = false;
            newEntries = reg.enum_entries.map((entry) => {
              const eKey = `enum_${reg.id}_${entry.value}`;
              if (enumKeys.includes(eKey) && result[eKey]) {
                changed = true;
                const tr = { ...(entry.translations ?? {}), ru: entry.title };
                return { ...entry, title: result[eKey], translations: tr };
              }
              return entry;
            });
            if (!changed) newEntries = reg.enum_entries;
          }

          return {
            ...reg,
            name: newName,
            description: newDescription,
            translations,
            enum_entries: newEntries,
          };
        });

        const updatedGroups = s.groups.map((group) => {
          const titleKey = `group_title_${group.id}`;
          const descKey = `group_desc_${group.id}`;
          const hasNewTitle = groupTitleKeys.includes(titleKey) && result[titleKey];
          const hasNewDesc = groupDescKeys.includes(descKey) && result[descKey];
          if (!hasNewTitle && !hasNewDesc) return group;

          let translations = { ...(group.translations ?? {}) };
          const ruTr = { ...(translations.ru ?? {}) };
          let newTitle = group.title;
          let newDescription = group.description;

          if (hasNewTitle) {
            ruTr.title = group.title;
            newTitle = result[titleKey];
          }
          if (hasNewDesc) {
            ruTr.description = group.description!;
            newDescription = result[descKey];
          }
          translations = { ...translations, ru: ruTr };

          return { ...group, title: newTitle, description: newDescription, translations };
        });

        return { registers: updatedRegisters, groups: updatedGroups };
      });

      buildAndSave(get);
      set({ translateResult: `Нормализовано → EN: ${translated} из ${totalStrings}` });
      setTimeout(() => set({ translateResult: null }), 4000);
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Ошибка перевода';
      set({ translateError: msg });
    } finally {
      set({ translating: false });
    }
  },

  importTemplate: async (file) => {
    set({ importing: true, importError: null });
    try {
      const data = await importTemplateApi(file);
      const include = (data as Record<string, unknown>).include as string | undefined;
      set({
        registers: data.registers,
        groups: data.groups ?? [],
        deviceInfo: { ...get().deviceInfo, ...data.device_info },
      });
      buildAndSave(get);
      if (include && data.registers.length === 0) {
        set({ importError: `Шаблон-обёртка: регистры находятся в ${include}. Загрузите этот файл для получения регистров.` });
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Ошибка импорта';
      set({ importError: msg });
    } finally {
      set({ importing: false });
    }
  },

  moveRegistersToGroup: (regIds, targetGroupId) => {
    set((s) => ({
      registers: s.registers.map((r) =>
        regIds.includes(r.id) ? { ...r, group: targetGroupId } : r,
      ),
    }));
    buildAndSave(get);
  },

  reorderRegister: (draggedId, targetId, position) => {
    if (draggedId === targetId) return;
    set((s) => {
      const regs = [...s.registers];
      const draggedIdx = regs.findIndex((r) => r.id === draggedId);
      const targetReg = regs.find((r) => r.id === targetId);
      if (draggedIdx === -1 || !targetReg) return s;

      const [dragged] = regs.splice(draggedIdx, 1);
      // Перемещаем в группу цели если отличается, сбрасываем param_order
      const movedReg = {
        ...dragged,
        group: targetReg.group,
        param_order: undefined,
      };

      let targetIdx = regs.findIndex((r) => r.id === targetId);
      if (targetIdx === -1) return s;
      if (position === 'after') targetIdx++;

      regs.splice(targetIdx, 0, movedReg);
      return { registers: regs };
    });
    buildAndSave(get);
  },

  setCustomSystemPrompt: (prompt) => {
    set({ customSystemPrompt: prompt });
    try {
      if (prompt === null) {
        localStorage.removeItem(CUSTOM_PROMPT_STORAGE_KEY);
      } else {
        localStorage.setItem(CUSTOM_PROMPT_STORAGE_KEY, prompt);
      }
    } catch { /* игнорируем */ }
  },

  propagateEnumTranslation: (englishTitle, lang, translation) => {
    set((s) => {
      let changed = false;
      const updated = s.registers.map((r) => {
        if (!r.enum_entries) return r;
        let entryChanged = false;
        const newEntries = r.enum_entries.map((e) => {
          if (e.title !== englishTitle) return e;
          const currentTr = e.translations?.[lang];
          if (currentTr === translation) return e;
          entryChanged = true;
          const tr = { ...(e.translations ?? {}) };
          if (translation) {
            tr[lang] = translation;
          } else {
            delete tr[lang];
          }
          return { ...e, translations: Object.keys(tr).length > 0 ? tr : undefined };
        });
        if (!entryChanged) return r;
        changed = true;
        return { ...r, enum_entries: newEntries };
      });
      return changed ? { registers: updated } : s;
    });
    buildAndSave(get);
  },

  resetAll: () => {
    // Сохраняем llmConfig — настройки LLM не сбрасываются
    const { llmConfig } = get();
    try {
      saveState({ registers: [], groups: [], deviceInfo: { name: '', id: '' }, llmConfig });
    } catch { /* игнорируем */ }
    set({
      files: [],
      registers: [],
      groups: [],
      deviceInfo: { name: '', id: '' },
      template: null,
      buildError: null,
      analyzeStatus: 'idle',
      analyzeProgress: null,
      analyzeError: null,
      highlightedRegisterId: null,
      expandedRows: new Set(),
      previewLang: 'en',
    });
  },

  triggerBuild: () => {
    if (buildTimeout) clearTimeout(buildTimeout);
    buildTimeout = setTimeout(async () => {
      const { registers, deviceInfo, groups } = get();
      if (registers.length === 0) {
        set({ template: null });
        return;
      }
      try {
        // Отправляем ВСЕ регистры — builder решает что включать
        // (каналы: все, disabled с enabled:false; параметры: только enabled)
        const template = await buildTemplate({ device_info: deviceInfo, registers, groups });
        set({ template, buildError: null });
      } catch (e) {
        const msg = e instanceof Error ? e.message : 'Неизвестная ошибка';
        set({ buildError: `Ошибка сборки шаблона: ${msg}` });
      }
    }, 300);
  },

  checkLlmStatus: () => {
    const { llmConfig } = get();
    // Всегда запрашиваем статус сервера (для версии и лимитов)
    fetchStatus()
      .then((s) => {
        const patch: Record<string, unknown> = {
          maxFileSizeMb: s.max_file_size_mb ?? 1,
          serverModel: s.server_model ?? null,
          appVersion: s.version ?? null,
        };
        // Если пользователь задал свой URL — LLM доступен без проверки сервера
        if (llmConfig.apiUrl) {
          patch.llmAvailable = true;
        } else {
          patch.llmAvailable = s.llm_available;
        }
        set(patch as Partial<TemplateStore>);
      })
      .catch(() => {
        // Сервер недоступен, но кастомный LLM всё равно работает
        if (llmConfig.apiUrl) {
          set({ llmAvailable: true });
        } else {
          set({ llmAvailable: null });
        }
      });
  },

  cancelAnalyze: () => {
    const controller = get().analyzeAbortController;
    if (controller) controller.abort();
    set((s) => ({
      analyzeStatus: 'idle',
      analyzeProgress: null,
      analyzeAbortController: null,
      analyzeLog: [...s.analyzeLog, `[${new Date().toLocaleTimeString()}] Анализ отменён пользователем`],
    }));
  },

  startAnalyze: () => {
    const { files, llmConfig, templateType, customSystemPrompt, languages } = get();
    if (files.length === 0) return;

    const isCustomLlm = !!llmConfig.apiUrl;
    const controller = new AbortController();
    const log = (msg: string) => set((s) => ({ analyzeLog: [...s.analyzeLog, `[${new Date().toLocaleTimeString()}] ${msg}`] }));

    set({
      analyzeAbortController: controller,
      analyzeStatus: 'loading',
      analyzeError: null,
      analyzeRequestId: null,
      analyzeProgress: null,
      analyzeLog: [],
    });

    log(`Начало анализа: ${files.length} файл(ов), тип=${templateType}, модель=${llmConfig.model || '(сервер)'}`);
    log(`Файлы: ${files.map((f) => `${f.name} (${(f.size / 1024).toFixed(0)} КБ)`).join(', ')}`);

    analyzeFiles(
      files,
      {
        templateType,
        llmApiUrl: llmConfig.apiUrl,
        llmApiKey: llmConfig.apiKey,
        llmModel: llmConfig.model,
        llmMaxTokens: llmConfig.maxTokens,
        llmTimeout: llmConfig.timeout,
        llmLegacyMaxTokens: llmConfig.legacyMaxTokens,
        llmTemperature: llmConfig.temperature,
        // Системный промпт передаём только при кастомном LLM
        systemPrompt: isCustomLlm ? (customSystemPrompt ?? undefined) : undefined,
        translationLanguages: languages.map((l) => l.code),
      },
      {
        onProgress: (progress) => {
          log(`${progress.stage}: ${progress.message}`);
          set({ analyzeProgress: progress });
        },
        onResult: (data) => {
          log(`Результат: ${data.registers.length} регистров, устройство="${data.device_info.name}"`);

          set({ registers: data.registers });
          set((s) => ({ deviceInfo: { ...s.deviceInfo, ...data.device_info } }));
          // Автогенерация groups из регистров (если groups пустые)
          if (get().groups.length === 0 && data.registers.length > 0) {
            const seen = new Map<string, string>();
            for (const reg of data.registers) {
              if (reg.group && !seen.has(reg.group)) {
                seen.set(reg.group, reg.group_title || reg.group);
              }
            }
            const autoGroups: RegisterGroup[] = [];
            let order = 0;
            for (const [id, title] of seen) {
              autoGroups.push({ id, title, order: order++, translations: {} });
            }
            if (autoGroups.length > 0) {
              set({ groups: autoGroups });
            }
          }
          buildAndSave(get);
        },
        onError: (error, requestId) => {
          log(`ОШИБКА: ${error}`);
          set({ analyzeError: error, analyzeStatus: 'error', analyzeRequestId: requestId ?? null });
        },
        onDone: () => {
          log('Анализ завершён успешно');
          set({ analyzeStatus: 'idle', analyzeAbortController: null });
        },
        onRequestId: (requestId) => {
          set({ analyzeRequestId: requestId });
        },
      },
      controller.signal,
    );
  },
}));

// При наличии сохранённых регистров — запускаем начальную сборку шаблона
if (_saved.registers && _saved.registers.length > 0) {
  useStore.getState().triggerBuild();
}

// Проверяем доступность LLM при старте
useStore.getState().checkLlmStatus();

// Очистка debounce-таймера при горячей перезагрузке (HMR),
// чтобы старый timeout не утекал при пересоздании модуля
if (import.meta.hot) {
  import.meta.hot.dispose(() => {
    if (buildTimeout) clearTimeout(buildTimeout);
  });
}
