import { useEffect, useState } from 'react';
import { useT } from '../i18n';
import { validateSchema, type BuildRequest } from '../api';

/** Переводит ошибку схемы: "path: i18n:key|p1=v1" → "path: переведённый текст" */
function translateSchemaError(error: string, t: (key: string, params?: Record<string, string | number>) => string): string {
  const colonIdx = error.indexOf(': i18n:');
  if (colonIdx === -1) return error;
  const path = error.slice(0, colonIdx);
  const i18nPart = error.slice(colonIdx + 2); // "i18n:key|p1=v1|p2=v2"
  const parts = i18nPart.slice(5).split('|'); // ["key", "p1=v1", "p2=v2"]
  const key = parts[0];
  const params: Record<string, string> = {};
  for (const p of parts.slice(1)) {
    const eq = p.indexOf('=');
    if (eq > 0) params[p.slice(0, eq)] = p.slice(eq + 1);
  }
  return `${path}: ${t(key, params)}`;
}

interface Props {
  isOpen: boolean;
  validationErrorCount: number;
  validationWarningCount: number;
  buildRequest: BuildRequest | null;
  onDownload: () => void;
  onCancel: () => void;
}

/** Модалка подтверждения скачивания с опциональной проверкой по схеме драйвера */
export default function ValidationGateModal({
  isOpen, validationErrorCount, validationWarningCount,
  buildRequest, onDownload, onCancel,
}: Props) {
  const t = useT();
  const [checkSchema, setCheckSchema] = useState(true);
  const [schemaErrors, setSchemaErrors] = useState<string[] | null>(null);
  const [schemaLoading, setSchemaLoading] = useState(false);

  const handleCheckSchema = async () => {
    if (!buildRequest) return;
    setSchemaLoading(true);
    try {
      const result = await validateSchema(buildRequest);
      setSchemaErrors(result.errors ?? []);
    } catch {
      setSchemaErrors(['Failed to validate schema']);
    }
    setSchemaLoading(false);
  };

  // Проверка по схеме включена по умолчанию — запускаем её при открытии модалки
  useEffect(() => {
    if (isOpen && checkSchema && schemaErrors === null && !schemaLoading && buildRequest) {
      void handleCheckSchema();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen]);

  if (!isOpen) return null;

  const hasIssues = validationErrorCount > 0 || validationWarningCount > 0
    || (schemaErrors !== null && schemaErrors.length > 0);

  const handleToggleSchema = () => {
    const next = !checkSchema;
    setCheckSchema(next);
    if (next && schemaErrors === null) {
      handleCheckSchema();
    }
  };

  const handleClose = () => {
    setCheckSchema(true);
    setSchemaErrors(null);
    setSchemaLoading(false);
    onCancel();
  };

  const handleDownload = () => {
    setCheckSchema(true);
    setSchemaErrors(null);
    setSchemaLoading(false);
    onDownload();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onClick={handleClose}>
      <div className="bg-white rounded-lg shadow-xl w-full max-w-md mx-4 p-5" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-sm font-semibold text-gray-900 mb-3">{t('validation.gateDownloadTitle')}</h3>

        {/* Статус валидации регистров */}
        {validationErrorCount > 0 && (
          <div className="flex items-center gap-1.5 text-sm text-red-600 mb-1">
            <span className="inline-block w-2 h-2 rounded-full bg-red-500" />
            {t('validation.errorCount', { count: validationErrorCount })}
          </div>
        )}
        {validationWarningCount > 0 && (
          <div className="flex items-center gap-1.5 text-sm text-amber-600 mb-1">
            <span className="inline-block w-2 h-2 rounded-full bg-amber-500" />
            {t('validation.warningCount', { count: validationWarningCount })}
          </div>
        )}
        {validationErrorCount === 0 && validationWarningCount === 0 && (
          <div className="flex items-center gap-1.5 text-sm text-green-600 mb-1">
            <span className="inline-block w-2 h-2 rounded-full bg-green-500" />
            {t('validation.registersOk')}
          </div>
        )}
        <div className="mb-3" />

        {/* Чекбокс проверки по схеме */}
        <label className="flex items-center gap-2 text-sm text-gray-700 mb-3 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={checkSchema}
            onChange={handleToggleSchema}
            className="rounded"
          />
          {t('validation.checkSchema')}
        </label>

        {/* Результат проверки схемы */}
        {checkSchema && schemaLoading && (
          <div className="text-xs text-gray-500 mb-3">{t('validation.schemaChecking')}</div>
        )}
        {checkSchema && schemaErrors !== null && !schemaLoading && (
          <div className={`mb-3 px-3 py-2 rounded text-xs ${
            schemaErrors.length === 0
              ? 'bg-green-50 border border-green-200 text-green-700'
              : 'bg-red-50 border border-red-200 text-red-700'
          }`}>
            {schemaErrors.length === 0 ? (
              t('validation.schemaOk')
            ) : (
              <>
                <div className="font-semibold mb-1">
                  {t('validation.schemaGateMessage', { count: schemaErrors.length })}
                </div>
                <ul className="space-y-0.5 max-h-32 overflow-y-auto font-mono">
                  {schemaErrors.slice(0, 10).map((e, i) => (
                    <li key={i}>{translateSchemaError(e, t)}</li>
                  ))}
                  {schemaErrors.length > 10 && <li>...</li>}
                </ul>
              </>
            )}
          </div>
        )}

        {/* Кнопки */}
        <div className="flex justify-end gap-2">
          <button
            onClick={handleClose}
            className="px-3 py-1.5 text-sm text-gray-600 bg-gray-100 rounded hover:bg-gray-200 transition-colors"
          >
            {t('confirm.cancel')}
          </button>
          <button
            onClick={handleDownload}
            className={`px-3 py-1.5 text-sm text-white rounded transition-colors ${
              hasIssues ? 'bg-amber-600 hover:bg-amber-700' : 'bg-green-600 hover:bg-green-700'
            }`}
          >
            {hasIssues ? t('validation.downloadAnyway') : t('toolbar.download')}
          </button>
        </div>
      </div>
    </div>
  );
}
