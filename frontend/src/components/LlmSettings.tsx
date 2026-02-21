import { useState } from 'react';
import { useStore } from '../store';
import { fetchModels, fetchPrompts } from '../api';
import { useT } from '../i18n';

interface LlmSettingsFieldsProps {
  /** Показывать как развёрнутую форму (без заголовка-аккордеона) */
  inline?: boolean;
}

/** Поля настроек LLM — переиспользуется в модалке и в LlmImportModal */
export default function LlmSettingsFields({ inline }: LlmSettingsFieldsProps) {
  const t = useT();
  const llmConfig = useStore((s) => s.llmConfig);
  const setLlmConfig = useStore((s) => s.setLlmConfig);

  const [models, setModels] = useState<string[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [modelsError, setModelsError] = useState<string | null>(null);

  const handleLoadModels = async () => {
    setModelsLoading(true);
    setModelsError(null);
    try {
      const list = await fetchModels({
        apiUrl: llmConfig.apiUrl,
        apiKey: llmConfig.apiKey,
      });
      setModels(list);
    } catch (e) {
      setModelsError(e instanceof Error ? e.message : t('api.modelsLoadError'));
    } finally {
      setModelsLoading(false);
    }
  };

  const inputClass = 'w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent';

  const content = (
    <div className="space-y-3">
      {!inline && (
        <p className="text-xs text-gray-400">
          {t('llmSettings.serverDefault')}
        </p>
      )}

      <div>
        <label className="block text-sm text-gray-600 mb-1">{t('llmSettings.apiUrl')}</label>
        <input
          type="text"
          value={llmConfig.apiUrl ?? ''}
          onChange={(e) => setLlmConfig({ apiUrl: e.target.value || undefined })}
          placeholder="https://api.openai.com/v1"
          className={inputClass}
        />
      </div>

      <div>
        <label className="block text-sm text-gray-600 mb-1">{t('llmSettings.apiKey')}</label>
        <input
          type="password"
          value={llmConfig.apiKey ?? ''}
          onChange={(e) => setLlmConfig({ apiKey: e.target.value || undefined })}
          placeholder="sk-..."
          className={inputClass}
        />
        <p className="text-[10px] text-gray-400 mt-0.5">
          {t('llmSettings.apiKeyHint')}
        </p>
      </div>

      <div>
        <label className="block text-sm text-gray-600 mb-1">{t('llmSettings.model')}</label>
        <div className="flex gap-1.5">
          <input
            type="text"
            list="llm-model-list"
            value={llmConfig.model ?? ''}
            onChange={(e) => setLlmConfig({ model: e.target.value || undefined })}
            placeholder="gpt-4o"
            className={inputClass}
          />
          <datalist id="llm-model-list">
            {models.map((m) => (
              <option key={m} value={m} />
            ))}
          </datalist>
          <button
            onClick={handleLoadModels}
            disabled={modelsLoading}
            className="px-2.5 py-2 border border-gray-300 rounded text-sm text-gray-600 hover:bg-gray-50 disabled:opacity-50 transition-colors flex-shrink-0"
            title={t('llmSettings.loadModels')}
          >
            {modelsLoading ? (
              <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
            ) : (
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
            )}
          </button>
        </div>
        {modelsError && <p className="text-xs text-red-500 mt-1">{modelsError}</p>}
        {models.length > 0 && !modelsError && (
          <p className="text-xs text-gray-400 mt-1">{t('llmSettings.modelsAvailable', { count: models.length })}</p>
        )}
      </div>

      <div className="flex gap-3">
        <div className="flex-1">
          <label className="block text-sm text-gray-600 mb-1">{t('llmSettings.maxTokens')}</label>
          <input
            type="number"
            value={llmConfig.maxTokens ?? ''}
            onChange={(e) => setLlmConfig({ maxTokens: e.target.value ? Number(e.target.value) : undefined })}
            placeholder="16384"
            min={1}
            className={inputClass}
          />
        </div>
        <div className="flex-1">
          <label className="block text-sm text-gray-600 mb-1">{t('llmSettings.timeout')}</label>
          <input
            type="number"
            value={llmConfig.timeout ?? ''}
            onChange={(e) => setLlmConfig({ timeout: e.target.value ? Number(e.target.value) : undefined })}
            placeholder="120"
            min={10}
            className={inputClass}
          />
        </div>
        <div className="flex-1">
          <label className="block text-sm text-gray-600 mb-1">{t('llmSettings.temperature')}</label>
          <input
            type="number"
            value={llmConfig.temperature ?? ''}
            onChange={(e) => setLlmConfig({ temperature: e.target.value ? Number(e.target.value) : undefined })}
            placeholder={t('llmSettings.temperaturePlaceholder')}
            min={0}
            max={2}
            step={0.1}
            className={inputClass}
          />
        </div>
      </div>

      <div>
        <label className="block text-sm text-gray-600 mb-1">{t('llmSettings.tokenParam')}</label>
        <select
          value={llmConfig.legacyMaxTokens ? 'legacy' : 'new'}
          onChange={(e) => setLlmConfig({ legacyMaxTokens: e.target.value === 'legacy' ? true : undefined })}
          className={inputClass}
        >
          <option value="new">{t('llmSettings.tokenParamNew')}</option>
          <option value="legacy">{t('llmSettings.tokenParamLegacy')}</option>
        </select>
        <p className="text-[10px] text-gray-400 mt-0.5">
          {t('llmSettings.tokenParamHint')}
        </p>
      </div>

    </div>
  );

  return content;
}

/** Секция редактора системного промпта */
function SystemPromptEditor() {
  const t = useT();
  const customSystemPrompt = useStore((s) => s.customSystemPrompt);
  const setCustomSystemPrompt = useStore((s) => s.setCustomSystemPrompt);
  const apiUrl = useStore((s) => s.llmConfig.apiUrl);
  const serverModel = useStore((s) => s.serverModel);

  const isCustomLlm = !!apiUrl;
  const [expanded, setExpanded] = useState(false);
  const [draft, setDraft] = useState(customSystemPrompt ?? '');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isCustom = customSystemPrompt !== null;

  const handleLoadDefault = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchPrompts();
      setDraft(data.system_prompt);
    } catch (e) {
      setError(e instanceof Error ? e.message : t('api.modelsLoadError'));
    } finally {
      setLoading(false);
    }
  };

  const handleSave = () => {
    const trimmed = draft.trim();
    if (trimmed) {
      setCustomSystemPrompt(trimmed);
    }
  };

  const handleReset = () => {
    setCustomSystemPrompt(null);
    setDraft('');
  };

  // При серверной модели промпт недоступен
  if (!isCustomLlm) {
    return (
      <div className="border-t border-gray-200 pt-3 mt-3">
        <p className="text-xs text-gray-400">
          {t('llmSettings.promptServerOnly', { model: serverModel ? ` (${serverModel})` : '' })}
        </p>
        <p className="text-[10px] text-gray-300 mt-1">
          {t('llmSettings.promptServerHint')}
        </p>
      </div>
    );
  }

  return (
    <div className="border-t border-gray-200 pt-3 mt-3">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="flex items-center justify-between w-full text-left"
      >
        <div className="flex items-center gap-2">
          <svg
            className={`w-3 h-3 text-gray-400 transition-transform duration-150 ${expanded ? 'rotate-90' : ''}`}
            fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
          </svg>
          <span className="text-sm text-gray-700 font-medium">{t('llmSettings.systemPrompt')}</span>
        </div>
        <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${
          isCustom
            ? 'bg-green-100 text-green-700'
            : 'bg-gray-100 text-gray-500'
        }`}>
          {isCustom ? t('llmSettings.promptCustom') : t('llmSettings.promptDefault')}
        </span>
      </button>

      {expanded && (
        <div className="mt-3 space-y-2">
          {!draft && !isCustom && (
            <p className="text-xs text-gray-400">
              {t('llmSettings.promptLoadHint')}
            </p>
          )}

          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={t('llmSettings.promptLoadHint')}
            rows={15}
            className="w-full border border-gray-300 rounded px-3 py-2 text-xs font-mono resize-y focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            style={{ minHeight: '200px' }}
          />

          <p className="text-[10px] text-gray-400">
            {t('llmSettings.promptPlaceholders')}
          </p>

          {error && <p className="text-xs text-red-500">{error}</p>}

          <div className="flex items-center gap-2">
            <button
              onClick={handleLoadDefault}
              disabled={loading}
              className="px-3 py-1.5 text-xs bg-gray-200 text-gray-700 rounded hover:bg-gray-300 disabled:opacity-50 transition-colors"
            >
              {loading ? t('llmSettings.promptLoading') : t('llmSettings.promptLoadDefault')}
            </button>
            <button
              onClick={handleSave}
              disabled={!draft.trim()}
              className="px-3 py-1.5 text-xs bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 transition-colors"
            >
              {t('llmSettings.promptSave')}
            </button>
            {isCustom && (
              <button
                onClick={handleReset}
                className="px-3 py-1.5 text-xs bg-red-100 text-red-700 rounded hover:bg-red-200 transition-colors"
              >
                {t('llmSettings.promptReset')}
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/** Модалка настроек LLM */
export function LlmSettingsModal({ isOpen, onClose }: { isOpen: boolean; onClose: () => void }) {
  const t = useT();
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onClick={onClose}>
      <div className="bg-white rounded-lg shadow-xl w-full max-w-lg mx-4 p-5 max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-base font-semibold text-gray-900">{t('llmSettings.title')}</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-lg font-bold">x</button>
        </div>
        <p className="text-xs text-gray-400 mb-3">
          {t('llmSettings.hint')}
        </p>
        <LlmSettingsFields inline />
        <SystemPromptEditor />
      </div>
    </div>
  );
}
