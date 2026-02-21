import { useState } from 'react';
import { useStore } from '../store';
import { useT } from '../i18n';
import type { EnumEntry } from '../types';
import { translateStrings } from '../api';

interface EnumEditorProps {
  entries: EnumEntry[];
  onChange: (entries: EnumEntry[]) => void;
  /** Доступные языки для переводов (из translations регистра) */
  availableLanguages?: string[];
}

/** Мини-таблица enum с переводами: | Значение | Title (EN) | Переводы | [x] | */
export default function EnumEditor({ entries, onChange, availableLanguages = [] }: EnumEditorProps) {
  const t = useT();
  const [expandedTranslations, setExpandedTranslations] = useState<Set<number>>(new Set());

  const updateEntry = (index: number, patch: Partial<EnumEntry>) => {
    const updated = entries.map((e, i) => (i === index ? { ...e, ...patch } : e));
    onChange(updated);
  };

  const addEntry = () => {
    const nextValue = entries.length > 0
      ? Math.max(...entries.map((e) => e.value)) + 1
      : 0;
    onChange([...entries, { value: nextValue, title: '' }]);
  };

  const removeEntry = (index: number) => {
    onChange(entries.filter((_, i) => i !== index));
  };

  const toggleTranslations = (index: number) => {
    setExpandedTranslations((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  };

  const propagateEnumTranslation = useStore((s) => s.propagateEnumTranslation);

  const updateEntryTranslation = (index: number, lang: string, value: string) => {
    const entry = entries[index];
    const tr = { ...(entry.translations ?? {}) };
    if (value) {
      tr[lang] = value;
    } else {
      delete tr[lang];
    }
    updateEntry(index, { translations: Object.keys(tr).length > 0 ? tr : undefined });
    // Авто-распространение: обновить перевод во всех регистрах с таким же enum title
    if (entry.title) {
      propagateEnumTranslation(entry.title, lang, value);
    }
  };

  const inputClass = 'border border-gray-300 rounded px-1.5 py-0.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-500';

  const hasAnyLangs = availableLanguages.length > 0;

  return (
    <div>
      {entries.length > 0 && (
        <table className="w-full text-xs mb-1">
          <thead>
            <tr className="text-gray-500">
              <th className="text-left font-medium px-1 w-16">{t('enum.value')}</th>
              <th className="text-left font-medium px-1">{t('enum.titleEn')}</th>
              {hasAnyLangs && <th className="text-left font-medium px-1 w-28">{t('enum.translations')}</th>}
              <th className="w-6"></th>
            </tr>
          </thead>
          <tbody>
            {entries.map((entry, i) => (
              <EnumRow
                key={i}
                index={i}
                entry={entry}
                availableLanguages={availableLanguages}
                isExpanded={expandedTranslations.has(i)}
                onToggle={() => toggleTranslations(i)}
                onUpdate={(patch) => updateEntry(i, patch)}
                onUpdateTranslation={(lang, value) => updateEntryTranslation(i, lang, value)}
                onRemove={() => removeEntry(i)}
                inputClass={inputClass}
                hasAnyLangs={hasAnyLangs}
              />
            ))}
          </tbody>
        </table>
      )}

      <button
        onClick={addEntry}
        className="text-xs text-blue-600 hover:text-blue-800"
      >
        {t('enum.addValue')}
      </button>
    </div>
  );
}

function EnumRow({
  entry,
  availableLanguages,
  isExpanded,
  onToggle,
  onUpdate,
  onUpdateTranslation,
  onRemove,
  inputClass,
  hasAnyLangs,
}: {
  index: number;
  entry: EnumEntry;
  availableLanguages: string[];
  isExpanded: boolean;
  onToggle: () => void;
  onUpdate: (patch: Partial<EnumEntry>) => void;
  onUpdateTranslation: (lang: string, value: string) => void;
  onRemove: () => void;
  inputClass: string;
  hasAnyLangs: boolean;
}) {
  const t = useT();
  // Бейджи переводов
  const tr = entry.translations ?? {};
  const trLangs = Object.keys(tr).filter((l) => tr[l]);

  // Счётчик регистров с таким же enum title (для бейджа распространения)
  const registers = useStore((s) => s.registers);
  const duplicateCount = entry.title
    ? registers.reduce((count, r) => {
        if (!r.enum_entries) return count;
        return count + r.enum_entries.filter((e) => e.title === entry.title).length;
      }, 0) - 1 // -1: не считаем текущий entry
    : 0;

  return (
    <>
      <tr>
        <td className="px-1 py-0.5">
          <input
            type="number"
            value={entry.value}
            onChange={(e) => onUpdate({ value: parseInt(e.target.value, 10) || 0 })}
            className={`${inputClass} w-14`}
          />
        </td>
        <td className="px-1 py-0.5">
          <input
            type="text"
            value={entry.title}
            onChange={(e) => onUpdate({ title: e.target.value })}
            placeholder="English"
            className={`${inputClass} w-full`}
          />
        </td>
        {hasAnyLangs && (
          <td className="px-1 py-0.5">
            <div className="flex items-center gap-1">
              <button
                onClick={onToggle}
                className="flex items-center gap-1 text-[10px] text-gray-500 hover:text-blue-600"
              >
                {trLangs.length > 0 ? (
                  <span className="flex gap-0.5 flex-wrap">
                    {trLangs.map((l) => (
                      <span key={l} className="bg-blue-50 text-blue-600 px-1 rounded">
                        {l}
                      </span>
                    ))}
                  </span>
                ) : (
                  <span className="text-gray-400">{t('enum.addTranslation')}</span>
                )}
              </button>
              {duplicateCount > 0 && (
                <span
                  className="text-[9px] bg-green-50 text-green-600 px-1 rounded cursor-help"
                  title={t('enum.duplicateHint', { title: entry.title, count: duplicateCount + 1 })}
                >
                  {'\u21C4'}{duplicateCount + 1}
                </span>
              )}
            </div>
          </td>
        )}
        <td className="px-1 py-0.5">
          <button
            onClick={onRemove}
            className="text-red-400 hover:text-red-600 text-xs font-bold"
            title={t('enum.delete')}
          >
            x
          </button>
        </td>
      </tr>
      {isExpanded && hasAnyLangs && (
        <tr>
          <td></td>
          <td colSpan={3} className="px-1 py-1">
            <div className="flex flex-wrap gap-2 bg-gray-50 rounded px-2 py-1.5">
              {availableLanguages.map((lang) => (
                <EnumTranslationField
                  key={lang}
                  lang={lang}
                  value={tr[lang] ?? ''}
                  englishTitle={entry.title}
                  onChange={(v) => onUpdateTranslation(lang, v)}
                  inputClass={inputClass}
                />
              ))}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

/** Поле перевода enum с кнопкой LLM-перевода */
function EnumTranslationField({
  lang, value, englishTitle, onChange, inputClass,
}: {
  lang: string; value: string; englishTitle: string;
  onChange: (v: string) => void; inputClass: string;
}) {
  const t = useT();
  const llmAvailable = useStore((s) => s.llmAvailable);
  const llmConfig = useStore((s) => s.llmConfig);
  const [loading, setLoading] = useState(false);

  const handleTranslate = async () => {
    if (!englishTitle) return;
    setLoading(true);
    try {
      const result = await translateStrings({ _: englishTitle }, lang, llmConfig);
      if (result._) onChange(result._);
    } catch { /* игнорируем */ }
    setLoading(false);
  };

  return (
    <div className="flex items-center gap-1">
      <span className="text-[10px] font-mono text-gray-400 uppercase w-5">{lang}</span>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={englishTitle || '...'}
        className={`${inputClass} w-28`}
      />
      {llmAvailable && englishTitle && (
        <button
          onClick={handleTranslate}
          disabled={loading}
          className="text-purple-400 hover:text-purple-600 disabled:opacity-50 flex-shrink-0"
          title={t('misc.translateTo', { lang })}
        >
          {loading ? (
            <svg className="w-3 h-3 animate-spin" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" strokeDasharray="31.4 31.4" /></svg>
          ) : (
            <svg className="w-3 h-3" viewBox="0 0 16 16" fill="currentColor"><path d="M8 1l1.5 4.5H14l-3.5 2.5L12 12.5 8 9.5l-4 3L5.5 8 2 5.5h4.5z" /></svg>
          )}
        </button>
      )}
    </div>
  );
}
