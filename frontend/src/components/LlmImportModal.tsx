import { useCallback, useEffect, useRef, useState } from 'react';
import { useStore } from '../store';
import FileUpload from './FileUpload';
import { LlmSettingsModal } from './LlmSettings';
import AnalyzeProgress from './AnalyzeProgress';
import ErrorDisplay from './ErrorDisplay';

/** Сворачиваемая панель лога анализа с кнопкой копирования */
function AnalyzeLog() {
  const analyzeLog = useStore((s) => s.analyzeLog);
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Автопрокрутка к последнему сообщению
  useEffect(() => {
    if (open && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [analyzeLog.length, open]);

  if (analyzeLog.length === 0) return null;

  const handleCopy = () => {
    navigator.clipboard.writeText(analyzeLog.join('\n')).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  };

  return (
    <div className="border border-gray-200 rounded text-xs">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-3 py-1.5 text-gray-500 hover:text-gray-700 hover:bg-gray-50 transition-colors"
      >
        <span>Лог ({analyzeLog.length})</span>
        <span className="text-[10px]">{open ? '▲' : '▼'}</span>
      </button>
      {open && (
        <div className="border-t border-gray-200">
          <div className="max-h-40 overflow-y-auto px-3 py-2 bg-gray-50 font-mono text-[11px] leading-relaxed text-gray-600 whitespace-pre-wrap">
            {analyzeLog.map((line, i) => (
              <div key={i} className={line.includes('ОШИБКА') ? 'text-red-600' : ''}>{line}</div>
            ))}
            <div ref={bottomRef} />
          </div>
          <div className="flex justify-end px-3 py-1 border-t border-gray-100">
            <button
              onClick={handleCopy}
              className="text-[11px] text-blue-500 hover:text-blue-700 transition-colors"
            >
              {copied ? 'Скопировано!' : 'Копировать лог'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

const TEMPLATE_TYPES = [
  { value: 'small' as const, label: 'Small', desc: '10-30 основных каналов' },
  { value: 'medium' as const, label: 'Medium', desc: 'Каналы + параметры конфигурации' },
  { value: 'full' as const, label: 'Full', desc: 'Все регистры' },
];

interface LlmImportModalProps {
  isOpen: boolean;
  onClose: () => void;
}

/** Модалка LLM-импорта: загрузка файлов, настройки, анализ */
export default function LlmImportModal({ isOpen, onClose }: LlmImportModalProps) {
  const files = useStore((s) => s.files);
  const templateType = useStore((s) => s.templateType);
  const setTemplateType = useStore((s) => s.setTemplateType);
  const analyzeStatus = useStore((s) => s.analyzeStatus);
  const analyzeError = useStore((s) => s.analyzeError);
  const startAnalyze = useStore((s) => s.startAnalyze);
  const cancelAnalyze = useStore((s) => s.cancelAnalyze);
  const llmAvailable = useStore((s) => s.llmAvailable);
  const llmConfig = useStore((s) => s.llmConfig);
  const checkLlmStatus = useStore((s) => s.checkLlmStatus);

  const [settingsOpen, setSettingsOpen] = useState(false);
  const [showCancelConfirm, setShowCancelConfirm] = useState(false);
  const prevStatusRef = useRef(analyzeStatus);
  const backdropRef = useRef<HTMLDivElement>(null);
  // Запоминаем, нужно ли закрыть модалку после подтверждения отмены
  const closeAfterCancelRef = useRef(false);

  useEffect(() => { checkLlmStatus(); }, [checkLlmStatus]);

  // Автозакрытие при успешном завершении анализа
  useEffect(() => {
    if (prevStatusRef.current === 'loading' && analyzeStatus === 'idle') {
      // Анализ завершился успешно (idle после loading)
      const regs = useStore.getState().registers;
      if (regs.length > 0) {
        onClose();
      }
    }
    prevStatusRef.current = analyzeStatus;
  }, [analyzeStatus, onClose]);

  // Скрываем диалог подтверждения, если анализ завершился
  useEffect(() => {
    if (analyzeStatus !== 'loading') setShowCancelConfirm(false);
  }, [analyzeStatus]);

  const handleAnalyze = useCallback(() => {
    startAnalyze();
  }, [startAnalyze]);

  /** Попытка закрыть модалку — с подтверждением, если анализ идёт */
  const handleClose = useCallback(() => {
    if (analyzeStatus === 'loading') {
      closeAfterCancelRef.current = true;
      setShowCancelConfirm(true);
    } else {
      onClose();
    }
  }, [analyzeStatus, onClose]);

  /** Подтверждение отмены анализа */
  const handleConfirmCancel = useCallback(() => {
    cancelAnalyze();
    setShowCancelConfirm(false);
    if (closeAfterCancelRef.current) {
      closeAfterCancelRef.current = false;
      onClose();
    }
  }, [cancelAnalyze, onClose]);

  /** Отмена подтверждения — продолжить анализ */
  const handleDismissConfirm = useCallback(() => {
    closeAfterCancelRef.current = false;
    setShowCancelConfirm(false);
  }, []);

  // Закрытие по клику на фон
  const handleBackdropClick = useCallback((e: React.MouseEvent) => {
    if (e.target === backdropRef.current) handleClose();
  }, [handleClose]);

  // Закрытие по Escape
  useEffect(() => {
    if (!isOpen) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (showCancelConfirm) {
          handleDismissConfirm();
        } else {
          handleClose();
        }
      }
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [isOpen, handleClose, showCancelConfirm, handleDismissConfirm]);

  if (!isOpen) return null;

  const llmReady = llmAvailable || !!llmConfig.apiUrl;

  return (
    <div
      ref={backdropRef}
      onClick={handleBackdropClick}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
    >
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-xl mx-4 max-h-[90vh] overflow-y-auto">
        {/* Шапка */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
          <h2 className="text-lg font-semibold text-gray-900">LLM Импорт</h2>
          <button
            onClick={handleClose}
            className="text-gray-400 hover:text-gray-600 text-xl leading-none"
            title="Закрыть"
          >
            &times;
          </button>
        </div>

        {/* Контент */}
        <div className="px-6 py-5 space-y-4">
          <FileUpload />

          {/* Тип шаблона */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Тип шаблона
            </label>
            <div className="flex gap-2">
              {TEMPLATE_TYPES.map((t) => (
                <button
                  key={t.value}
                  onClick={() => setTemplateType(t.value)}
                  className={`px-4 py-2 rounded text-sm transition-colors ${
                    templateType === t.value
                      ? 'bg-blue-600 text-white'
                      : 'bg-gray-200 text-gray-700 hover:bg-gray-300'
                  }`}
                  title={t.desc}
                >
                  {t.label}
                </button>
              ))}
            </div>
            <p className="text-xs text-gray-400 mt-1">
              {TEMPLATE_TYPES.find((t) => t.value === templateType)?.desc}
            </p>
            <button
              onClick={() => setSettingsOpen(true)}
              className="text-xs text-blue-500 hover:text-blue-700 mt-1 transition-colors"
            >
              + настройки LLM
            </button>
          </div>

          {/* Кнопка анализа */}
          <div>
            <button
              onClick={handleAnalyze}
              disabled={files.length === 0 || analyzeStatus === 'loading' || !llmReady}
              className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors inline-flex items-center gap-2"
            >
              {analyzeStatus === 'loading' && (
                <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
              )}
              {analyzeStatus === 'loading' ? 'Анализ...' : 'Анализировать'}
            </button>
            {!llmReady && (
              <p className="text-xs text-amber-600 mt-1.5">
                LLM не настроен. Задайте LLM_API_URL на сервере или укажите URL в{' '}
                <button onClick={() => setSettingsOpen(true)} className="underline hover:text-amber-800">настройках LLM</button>.
              </p>
            )}
          </div>

          {/* Прогресс */}
          <AnalyzeProgress onCancel={() => {
            closeAfterCancelRef.current = false;
            setShowCancelConfirm(true);
          }} />

          {/* Ошибка анализа (лог встроен внутри ErrorDisplay) */}
          {analyzeStatus === 'error' && analyzeError && (
            <div>
              <ErrorDisplay />
              <button
                onClick={handleAnalyze}
                className="mt-2 px-3 py-1 text-sm bg-red-100 text-red-700 rounded hover:bg-red-200 transition-colors"
              >
                Повторить
              </button>
            </div>
          )}

          {/* Лог анализа */}
          <AnalyzeLog />
        </div>
      </div>

      <LlmSettingsModal isOpen={settingsOpen} onClose={() => setSettingsOpen(false)} />

      {/* Диалог подтверждения отмены анализа */}
      {showCancelConfirm && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50">
          <div className="bg-white rounded-lg shadow-xl w-full max-w-sm mx-4 p-5">
            <p className="text-sm text-gray-800 mb-4">
              Анализ ещё выполняется. Прервать?
            </p>
            <div className="flex justify-end gap-2">
              <button
                onClick={handleDismissConfirm}
                className="px-4 py-2 text-sm bg-gray-200 text-gray-700 rounded hover:bg-gray-300 transition-colors"
              >
                Продолжить анализ
              </button>
              <button
                onClick={handleConfirmCancel}
                className="px-4 py-2 text-sm bg-red-600 text-white rounded hover:bg-red-700 transition-colors"
              >
                Прервать
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
