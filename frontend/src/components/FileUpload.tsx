import { useCallback, useEffect, useRef, useState } from 'react';
import { useStore } from '../store';

const ACCEPTED = '.pdf,.xlsx,.xls,.png,.jpg,.jpeg,.webp,.bmp';
const IMAGE_TYPES = ['image/png', 'image/jpeg', 'image/webp', 'image/bmp'];

/** Компонент загрузки файлов с drag-n-drop и вставкой из буфера */
export default function FileUpload() {
  const files = useStore((s) => s.files);
  const addFiles = useStore((s) => s.addFiles);
  const removeFile = useStore((s) => s.removeFile);
  const maxFileSizeMb = useStore((s) => s.maxFileSizeMb);
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [pasteFlash, setPasteFlash] = useState(false);
  const [sizeError, setSizeError] = useState<string | null>(null);

  const handleFiles = useCallback(
    (fileList: FileList | null) => {
      if (!fileList) return;
      const arr = Array.from(fileList);
      const maxBytes = maxFileSizeMb * 1024 * 1024;
      const oversized = arr.filter((f) => f.size > maxBytes);
      if (oversized.length > 0) {
        const names = oversized.map((f) => `${f.name} (${(f.size / 1024 / 1024).toFixed(1)} МБ)`).join(', ');
        setSizeError(
          `Файл${oversized.length > 1 ? 'ы' : ''} превыша${oversized.length > 1 ? 'ют' : 'ет'} лимит ${maxFileSizeMb} МБ: ${names}. ` +
          `Попробуйте разделить документ на части или конвертировать в изображения.`
        );
        const valid = arr.filter((f) => f.size <= maxBytes);
        if (valid.length > 0) addFiles(valid);
        return;
      }
      setSizeError(null);
      addFiles(arr);
    },
    [addFiles, maxFileSizeMb],
  );

  const handleDrop = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      setDragging(false);
      handleFiles(e.dataTransfer.files);
    },
    [handleFiles],
  );

  const handleDragOver = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragging(false);
  }, []);

  // Ctrl+V / Cmd+V — вставка изображения из буфера обмена
  useEffect(() => {
    const handlePaste = (e: ClipboardEvent) => {
      // Не перехватываем если фокус в input/textarea
      const tag = (e.target as HTMLElement).tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

      const items = e.clipboardData?.items;
      if (!items) return;

      const imageFiles: File[] = [];
      for (const item of items) {
        if (IMAGE_TYPES.includes(item.type)) {
          const file = item.getAsFile();
          if (file) {
            // Даём осмысленное имя файлу из буфера
            const ext = item.type.split('/')[1] || 'png';
            const named = new File([file], `clipboard-${Date.now()}.${ext}`, { type: item.type });
            imageFiles.push(named);
          }
        }
      }

      if (imageFiles.length > 0) {
        e.preventDefault();
        addFiles(imageFiles);
        // Визуальная обратная связь
        setPasteFlash(true);
        setTimeout(() => setPasteFlash(false), 600);
      }
    };
    window.addEventListener('paste', handlePaste);
    return () => window.removeEventListener('paste', handlePaste);
  }, [addFiles]);

  return (
    <div>
      {/* Зона drag-n-drop */}
      <div
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onClick={() => inputRef.current?.click()}
        className={`border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors ${
          pasteFlash
            ? 'border-green-500 bg-green-50'
            : dragging
              ? 'border-blue-500 bg-blue-50'
              : 'border-gray-300 hover:border-blue-400 hover:bg-gray-50'
        }`}
      >
        <div className="text-4xl mb-2">📎</div>
        <p className="text-gray-600 font-medium">
          Перетащите файлы сюда или нажмите для выбора
        </p>
        <p className="text-gray-400 text-sm mt-1">
          PDF, Excel, изображения (PNG, JPG, WebP, BMP) — до {maxFileSizeMb} МБ
        </p>
        <p className="text-gray-400 text-xs mt-0.5">
          Ctrl+V — вставка изображения из буфера
        </p>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={ACCEPTED}
          onChange={(e) => {
            handleFiles(e.target.files);
            e.target.value = '';
          }}
          className="hidden"
        />
      </div>

      {/* Ошибка размера файла */}
      {sizeError && (
        <div className="mt-2 bg-amber-50 text-amber-700 border border-amber-200 rounded p-2 text-xs flex items-start justify-between gap-2">
          <span>{sizeError}</span>
          <button onClick={() => setSizeError(null)} className="text-amber-500 hover:text-amber-700 flex-shrink-0 font-bold">&times;</button>
        </div>
      )}

      {/* Список загруженных файлов */}
      {files.length > 0 && (
        <ul className="mt-3 space-y-1">
          {files.map((file, index) => (
            <li
              key={`${file.name}-${index}`}
              className="flex items-center justify-between bg-gray-50 rounded px-3 py-2 text-sm"
            >
              <span className="text-gray-700 truncate mr-2">
                📎 {file.name}
                <span className="text-gray-400 ml-2">
                  ({(file.size / 1024).toFixed(1)} КБ)
                </span>
              </span>
              <button
                onClick={() => removeFile(index)}
                className="text-red-400 hover:text-red-600 flex-shrink-0 font-bold"
                title="Удалить файл"
              >
                ✕
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
