import { useStore } from '../store';

const STAGE_LABELS: Record<string, string> = {
  queued: 'В очереди',
  uploading: 'Загрузка',
  converting: 'Конвертация',
  analyzing: 'Анализ LLM',
  merging: 'Обработка',
  slow: 'Долгий анализ',
};

interface AnalyzeProgressProps {
  /** Callback при нажатии «Отменить» — вместо прямой отмены (для подтверждения) */
  onCancel?: () => void;
}

/** Компонент отображения прогресса анализа */
export default function AnalyzeProgress({ onCancel }: AnalyzeProgressProps) {
  const analyzeStatus = useStore((s) => s.analyzeStatus);
  const progress = useStore((s) => s.analyzeProgress);
  const requestId = useStore((s) => s.analyzeRequestId);
  const cancelAnalyze = useStore((s) => s.cancelAnalyze);

  if (analyzeStatus !== 'loading') return null;

  const isQueued = progress?.stage === 'queued';
  const isSlow = progress?.stage === 'slow';
  const queuePosition = progress?.queue_position;
  const queueEta = progress?.queue_eta;

  const hasProgress = progress?.current != null && progress?.total != null && progress.total > 0;
  const percent = hasProgress ? Math.round((progress!.current! / progress!.total!) * 100) : 0;

  const stageLabel = progress?.stage ? (STAGE_LABELS[progress.stage] || progress.stage) : '';

  const handleCancel = async () => {
    if (onCancel) {
      onCancel();
      return;
    }
    // Если в очереди — отменяем через API
    if (isQueued && requestId) {
      try {
        await fetch('/api/cancel-analyze', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ request_id: requestId }),
        });
      } catch { /* игнорируем */ }
    }
    cancelAnalyze();
  };

  return (
    <div className="mt-4 p-4 bg-gray-50 rounded-lg">
      {/* Очередь */}
      {isQueued && (
        <div className="mb-3">
          <div className="flex items-center gap-2 mb-1">
            <svg className="w-4 h-4 text-amber-500 animate-pulse" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm1-12a1 1 0 10-2 0v4a1 1 0 00.293.707l2.828 2.829a1 1 0 101.415-1.415L11 9.586V6z" clipRule="evenodd" />
            </svg>
            <p className="text-sm font-medium text-amber-700">Запрос в очереди</p>
          </div>
          <p className="text-sm text-gray-600">
            Позиция: <span className="font-semibold">{queuePosition ?? '?'}</span>
            {queueEta != null && (
              <span className="ml-2 text-gray-500">
                ~{queueEta >= 60 ? `${Math.ceil(queueEta / 60)} мин.` : `${queueEta} сек.`}
              </span>
            )}
          </p>
        </div>
      )}

      {/* Предупреждение о долгом анализе */}
      {isSlow && (
        <div className="mb-3 p-3 bg-amber-50 border border-amber-200 rounded">
          <p className="text-sm font-medium text-amber-800">
            Анализ занимает больше времени чем обычно
          </p>
          <p className="text-xs text-amber-600 mt-1">
            {progress?.message || 'LLM всё ещё обрабатывает запрос. Можно продолжить ожидание или отменить.'}
          </p>
        </div>
      )}

      {/* Текст прогресса */}
      {progress && !isQueued && !isSlow && (
        <div className="mb-2">
          <p className="text-sm font-medium text-gray-700">{stageLabel}</p>
          <p className="text-xs text-gray-500">{progress.message}</p>
          {progress.stage === 'analyzing' && (
            <p className="text-xs text-gray-400 mt-1 italic">
              Обычно анализ занимает 1–3 минуты. Для больших PDF — до 5 минут.
            </p>
          )}
        </div>
      )}

      {/* Прогресс-бар */}
      {!isQueued && (
        <div className="w-full bg-gray-200 rounded h-2 overflow-hidden">
          {hasProgress ? (
            <div
              className="bg-blue-600 h-2 rounded transition-all duration-300"
              style={{ width: `${percent}%` }}
            />
          ) : (
            <div className={`h-2 rounded ${isSlow ? 'bg-amber-500' : 'bg-blue-600'} animate-indeterminate`} />
          )}
        </div>
      )}

      {hasProgress && !isQueued && (
        <p className="text-xs text-gray-400 mt-1 text-right">{percent}%</p>
      )}

      {/* Кнопка отмены */}
      <button
        onClick={handleCancel}
        className={`mt-3 px-4 py-1.5 text-sm rounded transition-colors ${
          isSlow
            ? 'bg-amber-100 text-amber-800 hover:bg-amber-200'
            : 'bg-gray-200 text-gray-700 hover:bg-gray-300'
        }`}
      >
        Отменить
      </button>
    </div>
  );
}
