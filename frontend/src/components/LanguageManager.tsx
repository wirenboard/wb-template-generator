import { useState } from 'react';
import { useStore } from '../store';

interface Props {
  isOpen: boolean;
  onClose: () => void;
}

/** Модалка управления списком языков (сохраняется в localStorage) */
export default function LanguageManager({ isOpen, onClose }: Props) {
  const languages = useStore((s) => s.languages);
  const addLanguage = useStore((s) => s.addLanguage);
  const removeLanguage = useStore((s) => s.removeLanguage);
  const llmAvailable = useStore((s) => s.llmAvailable);
  const translating = useStore((s) => s.translating);
  const translateError = useStore((s) => s.translateError);
  const translateResult = useStore((s) => s.translateResult);
  const translateAll = useStore((s) => s.translateAll);

  const [newCode, setNewCode] = useState('');
  const [newLabel, setNewLabel] = useState('');

  if (!isOpen) return null;

  const handleAdd = () => {
    const code = newCode.trim().toLowerCase();
    const label = newLabel.trim() || code;
    if (!code) return;
    if (code === 'en') return; // en — базовый, не добавляем
    addLanguage({ code, label });
    setNewCode('');
    setNewLabel('');
  };

  const inputClass = 'border border-gray-300 rounded px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500';

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onClick={onClose}>
      <div className="bg-white rounded-lg shadow-xl w-full max-w-md mx-4 p-5" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-base font-semibold text-gray-900">Языки переводов</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-lg font-bold">x</button>
        </div>

        <p className="text-xs text-gray-400 mb-3">
          Базовый English (en) всегда включён. Добавьте языки для переводов имён и описаний регистров, групп.
          Список сохраняется в браузере.
        </p>

        {/* Статус перевода */}
        {translating && (
          <div className="mb-3 flex items-center gap-2 bg-blue-50 border border-blue-200 rounded px-3 py-2 text-xs text-blue-700">
            <svg className="w-3.5 h-3.5 animate-spin flex-shrink-0" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" strokeDasharray="31.4 31.4" /></svg>
            Отправлен запрос к LLM, переводим...
          </div>
        )}
        {translateError && !translating && (
          <div className="mb-3 bg-red-50 border border-red-200 rounded px-3 py-2 text-xs text-red-700">
            {translateError}
          </div>
        )}
        {translateResult && !translating && (
          <div className="mb-3 bg-green-50 border border-green-200 rounded px-3 py-2 text-xs text-green-700">
            {translateResult}
          </div>
        )}

        {languages.length > 0 ? (
          <div className="space-y-1.5 mb-4 max-h-60 overflow-y-auto">
            {languages.map((lang) => (
              <div key={lang.code} className="flex items-center gap-2 bg-gray-50 rounded px-3 py-1.5">
                <span className="text-xs font-mono text-gray-500 uppercase w-8">{lang.code}</span>
                <span className="text-sm text-gray-700 flex-1">{lang.label}</span>
                {llmAvailable && (
                  <button
                    onClick={() => translateAll(lang.code)}
                    disabled={translating}
                    className="px-2 py-0.5 text-[10px] bg-purple-50 text-purple-600 rounded hover:bg-purple-100 disabled:opacity-50 transition-colors"
                    title={`Перевести все пустые поля на ${lang.label}`}
                  >
                    {translating ? '...' : 'Перевести всё'}
                  </button>
                )}
                <button
                  onClick={() => removeLanguage(lang.code)}
                  className="text-red-400 hover:text-red-600 text-xs font-bold"
                  title={`Удалить ${lang.code}`}
                >
                  x
                </button>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-gray-400 mb-4 text-center py-3">
            Нет дополнительных языков.
          </p>
        )}

        <div className="border-t pt-3">
          <div className="text-xs font-medium text-gray-500 mb-2">Добавить язык</div>
          <div className="flex gap-2 items-end">
            <div className="w-20">
              <label className="text-xs text-gray-500">Код</label>
              <input
                type="text"
                value={newCode}
                onChange={(e) => setNewCode(e.target.value.toLowerCase().replace(/[^a-z]/g, '').slice(0, 5))}
                placeholder="ru"
                className={`${inputClass} w-full`}
                onKeyDown={(e) => { if (e.key === 'Enter') handleAdd(); }}
              />
            </div>
            <div className="flex-1">
              <label className="text-xs text-gray-500">Название</label>
              <input
                type="text"
                value={newLabel}
                onChange={(e) => setNewLabel(e.target.value)}
                placeholder="Русский (ru)"
                className={`${inputClass} w-full`}
                onKeyDown={(e) => { if (e.key === 'Enter') handleAdd(); }}
              />
            </div>
            <button
              onClick={handleAdd}
              disabled={!newCode.trim()}
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
