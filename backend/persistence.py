"""Модуль для персистентности метрик в JSON файлах.

Реализует файловое хранение метрик с поддержкой:
- Периодического сохранения текущих метрик (каждые 300 сек)
- Восстановления состояния при старте приложения
- Безопасного записи с атомарными операциями
- Логирования операций сохранения/загрузки
"""

import os
import json
import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, Callable, Awaitable
import tempfile
import shutil

logger = logging.getLogger(__name__)

class MetricsPersistence:
    """Класс для управления персистентностью метрик."""
    
    def __init__(self, base_path: str = "data/metrics"):
        """
        Инициализация модуля персистентности.
        
        Args:
            base_path: Базовая директория для хранения данных
        """
        self.base_path = Path(base_path)
        self.current_path = self.base_path / "current"
        
        # Создаем директории если их нет
        self.current_path.mkdir(parents=True, exist_ok=True)
        
        # Пути к основным файлам
        self.basic_metrics_file = self.current_path / "basic_metrics.json"
        self.llm_metrics_file = self.current_path / "llm_metrics.json"
        
        # Флаг активности автосохранения
        self._auto_save_task: Optional[asyncio.Task[None]] = None
        self._save_interval = 300  # 5 минут в секундах
        
        logger.info(f"Инициализация персистентности метрик в {self.base_path}")
    
    async def save_metrics(self, metrics_data: Dict[str, Any]) -> bool:
        """
        Сохраняет метрики в JSON файлы.
        
        Args:
            metrics_data: Словарь с метриками (basic, llm)
            
        Returns:
            True если сохранение прошло успешно
        """
        try:
            # Добавляем timestamp
            timestamp = datetime.now().isoformat()
            
            # Сохраняем базовые метрики
            if "basic" in metrics_data:
                basic_data = {
                    "timestamp": timestamp,
                    "data": metrics_data["basic"]
                }
                await self._save_json_atomic(self.basic_metrics_file, basic_data)
            
            # Сохраняем LLM метрики  
            if "llm" in metrics_data:
                llm_data = {
                    "timestamp": timestamp,
                    "data": metrics_data["llm"]
                }
                await self._save_json_atomic(self.llm_metrics_file, llm_data)
            
            logger.debug(f"Метрики сохранены в {timestamp}")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка сохранения метрик: {e}")
            return False
    
    async def load_metrics(self) -> Dict[str, Any]:
        """
        Загружает метрики из JSON файлов.
        
        Returns:
            Словарь с загруженными метриками или пустой словарь
        """
        result = {}
        
        try:
            # Загружаем базовые метрики
            basic_data = await self._load_json(self.basic_metrics_file)
            if basic_data and "data" in basic_data:
                result["basic"] = basic_data["data"]
                result["basic_timestamp"] = basic_data.get("timestamp")
            
            # Загружаем LLM метрики
            llm_data = await self._load_json(self.llm_metrics_file)
            if llm_data and "data" in llm_data:
                result["llm"] = llm_data["data"]
                result["llm_timestamp"] = llm_data.get("timestamp")
            
            if result:
                logger.info(f"Метрики успешно загружены: {list(result.keys())}")
            else:
                logger.info("Файлы метрик не найдены, начинаем с чистого состояния")
                
        except Exception as e:
            logger.error(f"Ошибка загрузки метрик: {e}")
            
        return result
    
    async def _save_json_atomic(self, file_path: Path, data: Dict[str, Any]) -> None:
        """
        Атомарное сохранение JSON файла через временный файл.
        
        Args:
            file_path: Путь к целевому файлу
            data: Данные для сохранения
        """
        # Создаем временный файл в той же директории
        temp_fd, temp_path = tempfile.mkstemp(
            suffix=".json.tmp",
            dir=file_path.parent
        )
        
        try:
            with os.fdopen(temp_fd, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())  # Принудительная запись на диск
            
            # Атомарное переименование
            shutil.move(temp_path, file_path)
            
        except Exception:
            # Очищаем временный файл при ошибке
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            raise
    
    async def _load_json(self, file_path: Path) -> Optional[Dict[str, Any]]:
        """
        Загрузка JSON файла.
        
        Args:
            file_path: Путь к файлу
            
        Returns:
            Загруженные данные или None если файл не найден/поврежден
        """
        if not file_path.exists():
            return None
            
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data if isinstance(data, dict) else None
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Не удалось загрузить {file_path}: {e}")
            return None
    
    async def start_auto_save(self, get_metrics_func: Callable[[], Awaitable[Dict[str, Any]]]) -> None:
        """
        Запускает автоматическое периодическое сохранение метрик.
        
        Args:
            get_metrics_func: Функция для получения текущих метрик
        """
        if self._auto_save_task is not None:
            logger.warning("Автосохранение уже запущено")
            return
        
        async def auto_save_loop() -> None:
            logger.info(f"Запуск автосохранения метрик каждые {self._save_interval} секунд")
            
            while True:
                try:
                    await asyncio.sleep(self._save_interval)
                    
                    # Получаем текущие метрики
                    current_metrics = get_metrics_func()
                    
                    # Сохраняем
                    await self.save_metrics(current_metrics)
                    
                except asyncio.CancelledError:
                    logger.info("Автосохранение метрик остановлено")
                    break
                except Exception as e:
                    logger.error(f"Ошибка в автосохранении метрик: {e}")
                    # Продолжаем работу несмотря на ошибку
        
        self._auto_save_task = asyncio.create_task(auto_save_loop())
    
    async def stop_auto_save(self) -> None:
        """Останавливает автоматическое сохранение."""
        if self._auto_save_task is not None:
            self._auto_save_task.cancel()
            try:
                await self._auto_save_task
            except asyncio.CancelledError:
                pass
            self._auto_save_task = None
            logger.info("Автосохранение метрик остановлено")
    
    def get_storage_info(self) -> Dict[str, Any]:
        """
        Возвращает информацию о хранилище метрик.
        
        Returns:
            Словарь с информацией о файлах и размерах
        """
        info: Dict[str, Any] = {
            "base_path": str(self.base_path),
            "files": {},
            "total_size_bytes": 0
        }
        
        # Проверяем основные файлы
        for name, path in [
            ("basic_metrics", self.basic_metrics_file),
            ("llm_metrics", self.llm_metrics_file)
        ]:
            if path.exists():
                stat = path.stat()
                info["files"][name] = {
                    "path": str(path),
                    "size_bytes": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
                }
                info["total_size_bytes"] += stat.st_size
            else:
                info["files"][name] = {
                    "path": str(path),
                    "exists": False
                }
        
        return info

# Глобальный экземпляр для использования в приложении
_persistence: Optional[MetricsPersistence] = None

def get_persistence() -> MetricsPersistence:
    """Возвращает глобальный экземпляр MetricsPersistence."""
    global _persistence
    if _persistence is None:
        _persistence = MetricsPersistence()
    return _persistence

async def initialize_persistence() -> None:
    """Инициализация модуля персистентности."""
    get_persistence()  # Создаем экземпляр для инициализации
    logger.info("Модуль персистентности инициализирован")
    
async def cleanup_persistence() -> None:
    """Очистка ресурсов при завершении работы."""
    persistence = get_persistence()
    await persistence.stop_auto_save()
    logger.info("Модуль персистентности очищен")