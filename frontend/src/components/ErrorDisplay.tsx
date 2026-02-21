import { useState } from 'react';
import { useStore } from '../store';
import { useT } from '../i18n';

export default function ErrorDisplay() {
  const t = useT();
  const error = useStore((s) => s.analyzeError);
  const requestId = useStore((s) => s.analyzeRequestId);
  const analyzeLog = useStore((s) => s.analyzeLog);
  const setAnalyzeError = useStore((s) => s.setAnalyzeError);
  const [copied, setCopied] = useState(false);

  if (!error) return null;

  const handleCopy = () => {
    const lines: string[] = [
      t('error.reportHeader'),
    ];
    if (requestId) lines.push(`Request ID: ${requestId}`);
    lines.push(`${t('error.time')}: ${new Date().toISOString()}`);
    lines.push(`URL: ${window.location.href}`);
    if (analyzeLog.length > 0) {
      lines.push('', t('error.logSection'), ...analyzeLog);
    }
    navigator.clipboard.writeText(lines.join('\n') + '\n').then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  return (
    <div className="mt-4 p-4 bg-red-50 border border-red-200 rounded-lg">
      <div className="flex items-start justify-between">
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-red-800">{t('error.analyzeTitle')}</p>
          <p className="mt-1 text-sm text-red-700 whitespace-pre-wrap break-words">{error}</p>
          {requestId && (
            <p className="mt-2 text-xs text-red-500 font-mono">
              Request ID: {requestId}
            </p>
          )}
        </div>
        <button
          onClick={() => setAnalyzeError(null)}
          className="ml-2 text-red-400 hover:text-red-600 text-lg leading-none flex-shrink-0"
        >
          &times;
        </button>
      </div>
      <button
        onClick={handleCopy}
        className="mt-3 px-3 py-1.5 text-xs bg-red-100 text-red-700 rounded hover:bg-red-200 transition-colors"
      >
        {copied ? t('error.copied') : t('error.copyForSupport')}
      </button>
    </div>
  );
}
