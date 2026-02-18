import { useState, useEffect } from 'react';
import { useStore } from '../store';
import type { RegisterGroup } from '../types';
import { translateStrings } from '../api';

interface GroupManagerProps {
  isOpen: boolean;
  onClose: () => void;
}

/** Модалка управления группами — автоматически подтягивает группы из регистров */
export default function GroupManager({ isOpen, onClose }: GroupManagerProps) {
  const groups = useStore((s) => s.groups);
  const registers = useStore((s) => s.registers);
  const setGroups = useStore((s) => s.setGroups);
  const updateGroup = useStore((s) => s.updateGroup);
  const removeGroup = useStore((s) => s.removeGroup);

  // При открытии — синхронизируем группы из регистров
  useEffect(() => {
    if (!isOpen) return;

    // Берём актуальные данные напрямую из store (не из closure)
    const state = useStore.getState();
    const currentGroups = state.groups;
    const currentRegisters = state.registers;

    const existingIds = new Set(currentGroups.map((g) => g.id));
    const fromRegisters = new Set(currentRegisters.map((r) => r.group).filter(Boolean));

    // Добавляем группы из регистров, которых ещё нет в store
    const newGroups: RegisterGroup[] = [];
    for (const groupId of fromRegisters) {
      if (!existingIds.has(groupId)) {
        const sampleReg = currentRegisters.find((r) => r.group === groupId);
        newGroups.push({
          id: groupId,
          title: sampleReg?.group_title || groupId,
          order: currentGroups.length + newGroups.length,
        });
      }
    }

    if (newGroups.length > 0) {
      state.setGroups([...currentGroups, ...newGroups]);
    }
  }, [isOpen]);

  const [newId, setNewId] = useState('');
  const [newTitle, setNewTitle] = useState('');

  if (!isOpen) return null;

  const handleAdd = () => {
    const id = newId.trim() || newTitle.trim().toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '');
    if (!id || !newTitle.trim()) return;
    if (groups.some((g) => g.id === id)) return;

    setGroups([...groups, {
      id,
      title: newTitle.trim(),
      order: groups.length,
    }]);
    setNewId('');
    setNewTitle('');
  };

  const moveGroup = (index: number, direction: -1 | 1) => {
    const newIndex = index + direction;
    if (newIndex < 0 || newIndex >= groups.length) return;
    const reordered = [...groups];
    [reordered[index], reordered[newIndex]] = [reordered[newIndex], reordered[index]];
    setGroups(reordered.map((g, i) => ({ ...g, order: i })));
  };

  // Считаем количество регистров в каждой группе
  const groupCounts = new Map<string, number>();
  for (const reg of registers) {
    groupCounts.set(reg.group, (groupCounts.get(reg.group) || 0) + 1);
  }

  const inputClass = 'border border-gray-300 rounded px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500';

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onClick={onClose}>
      <div className="bg-white rounded-lg shadow-xl w-full max-w-2xl mx-4 p-5 max-h-[80vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-base font-semibold text-gray-900">Управление группами</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-lg font-bold">x</button>
        </div>

        <p className="text-xs text-gray-400 mb-3">
          Группы подтягиваются из регистров автоматически. Здесь можно задать title, description, переводы и порядок.
        </p>

        {/* Список групп — с иерархической вложенностью */}
        {groups.length > 0 ? (
          <div className="space-y-2 mb-4">
            {(() => {
              // Строим иерархический порядок отображения
              type HItem = { group: RegisterGroup; level: number; flatIndex: number };
              const result: HItem[] = [];
              const topLevel = groups.filter((g) => !g.parent_group);
              const childrenOf = (pid: string) => groups.filter((g) => g.parent_group === pid);

              const addTree = (g: RegisterGroup, level: number) => {
                result.push({ group: g, level, flatIndex: groups.indexOf(g) });
                for (const child of childrenOf(g.id)) addTree(child, level + 1);
              };
              for (const g of topLevel) addTree(g, 0);

              // Сироты (parent_group указан, но родителя нет)
              const added = new Set(result.map((r) => r.group.id));
              for (const g of groups) {
                if (!added.has(g.id)) result.push({ group: g, level: 0, flatIndex: groups.indexOf(g) });
              }

              return result.map(({ group, level, flatIndex }) => (
                <GroupRow
                  key={group.id}
                  group={group}
                  level={level}
                  count={groupCounts.get(group.id) || 0}
                  index={flatIndex}
                  total={groups.length}
                  onUpdate={(patch) => updateGroup(group.id, patch)}
                  onRemove={() => removeGroup(group.id)}
                  onMove={(dir) => moveGroup(flatIndex, dir)}
                />
              ));
            })()}
          </div>
        ) : (
          <p className="text-sm text-gray-400 mb-4 text-center py-3">
            Нет групп. Создайте группу ниже или задайте в таблице регистров.
          </p>
        )}

        {/* Добавление группы */}
        <div className="border-t pt-3">
          <div className="text-xs font-medium text-gray-500 mb-2">Новая группа</div>
          <div className="flex gap-2 items-end">
            <div className="w-28">
              <label className="text-xs text-gray-500">ID</label>
              <input
                type="text"
                value={newId}
                onChange={(e) => setNewId(e.target.value)}
                placeholder="auto"
                className={`${inputClass} w-full`}
              />
            </div>
            <div className="flex-1">
              <label className="text-xs text-gray-500">Title (EN)</label>
              <input
                type="text"
                value={newTitle}
                onChange={(e) => setNewTitle(e.target.value)}
                placeholder="Group title"
                className={`${inputClass} w-full`}
              />
            </div>
            <button
              onClick={handleAdd}
              disabled={!newTitle.trim()}
              className="px-3 py-1 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              +
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

/** Строка группы в списке */
function GroupRow({
  group,
  level,
  count,
  index,
  total,
  onUpdate,
  onRemove,
  onMove,
}: {
  group: RegisterGroup;
  level: number;
  count: number;
  index: number;
  total: number;
  onUpdate: (patch: Partial<RegisterGroup>) => void;
  onRemove: () => void;
  onMove: (dir: -1 | 1) => void;
}) {
  const [showTranslations, setShowTranslations] = useState(false);
  const [showLangAdd, setShowLangAdd] = useState(false);

  const inputClass = 'border border-gray-200 rounded px-1.5 py-0.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-500';

  const translations = group.translations ?? {};
  const langs = Object.keys(translations).sort();

  const addLang = (code: string) => {
    if (!code || translations[code]) return;
    onUpdate({ translations: { ...translations, [code]: {} } });
    setShowLangAdd(false);
  };

  const removeLang = (code: string) => {
    const next = { ...translations };
    delete next[code];
    onUpdate({ translations: Object.keys(next).length > 0 ? next : undefined });
  };

  const updateTranslation = (lang: string, field: 'title' | 'description', value: string) => {
    const current = translations[lang] ?? {};
    onUpdate({
      translations: {
        ...translations,
        [lang]: { ...current, [field]: value || undefined },
      },
    });
  };

  const storeLanguages = useStore((s) => s.languages);
  const availableLangs = storeLanguages.filter((l) => !translations[l.code]);

  return (
    <div className={`rounded px-2 py-1.5 ${level > 0 ? 'bg-gray-50/60 border-l-2 border-gray-200' : 'bg-gray-50'}`} style={level > 0 ? { marginLeft: level * 24 } : undefined}>
      <div className="flex items-center gap-2">
        <div className="flex flex-col">
          <button
            onClick={() => onMove(-1)}
            disabled={index === 0}
            className="text-gray-400 hover:text-gray-600 disabled:opacity-30 text-[10px] leading-none"
          >
            {'\u25B2'}
          </button>
          <button
            onClick={() => onMove(1)}
            disabled={index === total - 1}
            className="text-gray-400 hover:text-gray-600 disabled:opacity-30 text-[10px] leading-none"
          >
            {'\u25BC'}
          </button>
        </div>
        <span className="text-xs text-gray-400 w-20 truncate" title={group.id}>{group.id}</span>
        <span className="text-[10px] text-gray-300 w-4">{count}</span>
        <input
          type="text"
          value={group.title}
          onChange={(e) => onUpdate({ title: e.target.value })}
          className={`${inputClass} flex-1`}
          placeholder="Title (EN)"
        />
        <input
          type="text"
          value={group.description ?? ''}
          onChange={(e) => onUpdate({ description: e.target.value || undefined })}
          className={`${inputClass} flex-1`}
          placeholder="Description (EN)"
        />
        <button
          onClick={() => setShowTranslations(!showTranslations)}
          className={`text-[10px] px-1.5 py-0.5 rounded transition-colors ${
            langs.length > 0 ? 'bg-blue-50 text-blue-600' : 'text-gray-400 hover:text-blue-500'
          }`}
          title="Переводы"
        >
          {langs.length > 0 ? langs.map((l) => l.toUpperCase()).join(', ') : 'i18n'}
        </button>
        <button
          onClick={onRemove}
          className="text-red-400 hover:text-red-600 text-xs font-bold flex-shrink-0"
          title="Удалить группу"
        >
          x
        </button>
      </div>

      {showTranslations && (
        <div className="mt-2 ml-8 space-y-1.5">
          {langs.map((lang) => (
            <GroupTranslationRow
              key={lang}
              lang={lang}
              titleValue={translations[lang]?.title ?? ''}
              descValue={translations[lang]?.description ?? ''}
              englishTitle={group.title}
              englishDesc={group.description}
              onUpdateTitle={(v) => updateTranslation(lang, 'title', v)}
              onUpdateDesc={(v) => updateTranslation(lang, 'description', v)}
              onRemove={() => removeLang(lang)}
              inputClass={inputClass}
            />
          ))}

          <div className="relative inline-block">
            <button
              onClick={() => setShowLangAdd(!showLangAdd)}
              className="text-[10px] text-blue-600 hover:text-blue-800"
            >
              + язык
            </button>
            {showLangAdd && (
              <div className="absolute z-10 mt-1 bg-white border border-gray-200 rounded shadow-lg py-1 w-24">
                {availableLangs.map((l) => (
                  <button
                    key={l.code}
                    onClick={() => addLang(l.code)}
                    className="block w-full text-left px-2 py-0.5 text-xs hover:bg-blue-50"
                  >
                    {l.label}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/** Строка перевода группы с кнопками LLM-перевода */
function GroupTranslationRow({
  lang, titleValue, descValue, englishTitle, englishDesc,
  onUpdateTitle, onUpdateDesc, onRemove, inputClass,
}: {
  lang: string; titleValue: string; descValue: string;
  englishTitle: string; englishDesc?: string;
  onUpdateTitle: (v: string) => void; onUpdateDesc: (v: string) => void;
  onRemove: () => void; inputClass: string;
}) {
  const llmAvailable = useStore((s) => s.llmAvailable);
  const llmConfig = useStore((s) => s.llmConfig);
  const [loading, setLoading] = useState(false);

  const handleTranslate = async () => {
    const strings: Record<string, string> = {};
    if (englishTitle && !titleValue) strings.title = englishTitle;
    if (englishDesc && !descValue) strings.desc = englishDesc;
    if (Object.keys(strings).length === 0) return;
    setLoading(true);
    try {
      const result = await translateStrings(strings, lang, llmConfig);
      if (result.title) onUpdateTitle(result.title);
      if (result.desc) onUpdateDesc(result.desc);
    } catch { /* игнорируем */ }
    setLoading(false);
  };

  return (
    <div className="flex items-center gap-2">
      <span className="text-[10px] font-mono text-gray-400 uppercase w-5">{lang}</span>
      <input
        type="text"
        value={titleValue}
        onChange={(e) => onUpdateTitle(e.target.value)}
        className={`${inputClass} flex-1`}
        placeholder={`Title (${lang})`}
      />
      <input
        type="text"
        value={descValue}
        onChange={(e) => onUpdateDesc(e.target.value)}
        className={`${inputClass} flex-1`}
        placeholder={`Description (${lang})`}
      />
      {llmAvailable && (
        <button
          onClick={handleTranslate}
          disabled={loading}
          className="text-purple-400 hover:text-purple-600 disabled:opacity-50 flex-shrink-0"
          title={`Перевести на ${lang}`}
        >
          {loading ? (
            <svg className="w-3 h-3 animate-spin" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" strokeDasharray="31.4 31.4" /></svg>
          ) : (
            <svg className="w-3 h-3" viewBox="0 0 16 16" fill="currentColor"><path d="M8 1l1.5 4.5H14l-3.5 2.5L12 12.5 8 9.5l-4 3L5.5 8 2 5.5h4.5z" /></svg>
          )}
        </button>
      )}
      <button
        onClick={onRemove}
        className="text-red-400 hover:text-red-600 text-[10px] font-bold"
        title={`Удалить ${lang}`}
      >
        x
      </button>
    </div>
  );
}
