"""Модуль для агрегации метрик по временным периодам."""

import asyncio
import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class MetricsAggregator:
    """Класс для агрегации метрик по временным периодам."""

    def __init__(self, base_path: str = "data/metrics"):
        """Инициализация агрегатора метрик."""
        self.base_path = Path(base_path)

        # Директории для разных уровней агрегации
        self.hourly_path = self.base_path / "hourly"
        self.daily_path = self.base_path / "daily"
        self.weekly_path = self.base_path / "weekly"
        self.monthly_path = self.base_path / "monthly"

        # Создаем директории
        for path in [
            self.hourly_path,
            self.daily_path,
            self.weekly_path,
            self.monthly_path,
        ]:
            path.mkdir(parents=True, exist_ok=True)

        # Ограничения хранения (в часах/днях/неделях)
        self.retention_limits = {
            "hourly": 72,  # 72 часа (3 дня)
            "daily": 90,  # 90 дней (~3 месяца)
            "weekly": 52,  # 52 недели (1 год)
            "monthly": 999999,  # Месячные - без ограничений
        }

        # Максимальный размер в байтах (100MB)
        self.max_total_size = 100 * 1024 * 1024

        # Задача агрегации
        self._aggregation_task: Optional[asyncio.Task[None]] = None

        logger.info(f"Инициализация агрегатора метрик в {self.base_path}")

    async def start_aggregation(
        self, get_metrics_func: Callable[[], Dict[str, Any]]
    ) -> None:
        """Запускает автоматическую агрегацию метрик."""
        if self._aggregation_task is not None:
            logger.warning("Агрегация уже запущена")
            return

        async def aggregation_loop() -> None:
            logger.info("Запуск автоматической агрегации метрик")

            while True:
                try:
                    # Ждем до начала следующего часа
                    next_hour = self._get_next_hour()
                    sleep_seconds = (next_hour - datetime.now()).total_seconds()

                    if sleep_seconds > 0:
                        await asyncio.sleep(sleep_seconds)

                    # Выполняем почасовую агрегацию
                    await self._perform_hourly_aggregation(get_metrics_func)

                    # Выполняем дневную агрегацию (в начале нового дня)
                    await self._perform_daily_aggregation_if_needed()

                    # Очистка старых данных
                    await self._cleanup_old_data()

                    # Контроль размера
                    await self._enforce_size_limits()

                except asyncio.CancelledError:
                    logger.info("Автоматическая агрегация остановлена")
                    break
                except Exception as e:
                    logger.error(f"Ошибка в агрегации метрик: {e}")
                    # Продолжаем работу несмотря на ошибки
                    await asyncio.sleep(300)  # Ждем 5 минут перед повтором

        self._aggregation_task = asyncio.create_task(aggregation_loop())

    async def stop_aggregation(self) -> None:
        """Останавливает автоматическую агрегацию."""
        if self._aggregation_task is not None:
            self._aggregation_task.cancel()
            try:
                await self._aggregation_task
            except asyncio.CancelledError:
                pass
            self._aggregation_task = None
            logger.info("Автоматическая агрегация остановлена")

    async def _perform_hourly_aggregation(
        self, get_metrics_func: Callable[[], Dict[str, Any]]
    ) -> None:
        """Выполняет почасовую агрегацию текущих метрик."""
        try:
            # Получаем текущие метрики
            current_metrics = get_metrics_func()

            # Формируем имя файла для текущего часа
            now = datetime.now()
            hour_key = now.strftime("%Y-%m-%d_%H")
            hour_file = self.hourly_path / f"{hour_key}.json"

            # Создаем агрегированные данные
            aggregated_data = {
                "timestamp": now.isoformat(),
                "period": "hour",
                "period_key": hour_key,
                "basic": current_metrics.get("basic", {}),
                "llm": current_metrics.get("llm", {}),
                "summary": self._create_hourly_summary(current_metrics),
            }

            # Сохраняем файл
            await self._save_aggregated_data(hour_file, aggregated_data)

            logger.debug(f"Почасовая агрегация выполнена: {hour_key}")

        except Exception as e:
            logger.error(f"Ошибка почасовой агрегации: {e}")

    def _create_hourly_summary(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        """Создает краткую сводку для почасовой агрегации."""
        basic = metrics.get("basic", {})
        llm = metrics.get("llm", {})

        return {
            "requests_total": basic.get("counters", {}).get("analyze_requests", 0),
            "errors_total": basic.get("counters", {}).get("analyze_errors", 0),
            "error_rate_percent": round(
                basic.get("counters", {}).get("analyze_errors", 0)
                / max(1, basic.get("counters", {}).get("analyze_requests", 0))
                * 100,
                2,
            ),
            "llm_requests_total": llm.get("counters", {}).get("llm_requests", 0),
            "tokens_total": llm.get("tokens", {}).get("total_tokens", 0),
            "registers_extracted": llm.get("processing", {}).get(
                "registers_extracted", 0
            ),
            "monitoring_page_views": basic.get("counters", {}).get(
                "monitoring_page_views", 0
            ),
            "rate_limit_hits": basic.get("counters", {}).get("rate_limit_hits", 0),
        }

    async def _perform_daily_aggregation_if_needed(self) -> None:
        """Выполняет дневную агрегацию если начался новый день."""
        try:
            now = datetime.now()

            # Проверяем, начался ли новый день (запускаем агрегацию в 00:00-01:00)
            if now.hour != 0:
                return

            # Формируем данные за вчерашний день
            yesterday = now.date() - timedelta(days=1)
            day_key = yesterday.strftime("%Y-%m-%d")
            day_file = self.daily_path / f"{day_key}.json"

            # Если дневной файл уже существует, пропускаем
            if day_file.exists():
                logger.debug(f"Дневная агрегация для {day_key} уже выполнена")
                return

            # Собираем все почасовые данные за вчерашний день
            hourly_data = await self._collect_hourly_data_for_day(yesterday)

            if not hourly_data:
                logger.warning(f"Нет почасовых данных для дневной агрегации {day_key}")
                return

            # Создаем дневную агрегацию
            daily_aggregated = {
                "timestamp": now.isoformat(),
                "period": "day",
                "period_key": day_key,
                "date": yesterday.isoformat(),
                "hours_aggregated": len(hourly_data),
                "summary": self._create_daily_summary(hourly_data),
                "hourly_breakdown": self._create_hourly_breakdown(hourly_data),
            }

            # Сохраняем дневные данные
            await self._save_aggregated_data(day_file, daily_aggregated)

            logger.info(
                f"Дневная агрегация выполнена: {day_key} ({len(hourly_data)} часов)"
            )

        except Exception as e:
            logger.error(f"Ошибка дневной агрегации: {e}")

    async def _collect_hourly_data_for_day(
        self, target_date: date
    ) -> List[Dict[str, Any]]:
        """Собирает все почасовые данные за указанный день."""
        return await asyncio.to_thread(
            self._collect_hourly_data_for_day_sync, target_date
        )

    def _collect_hourly_data_for_day_sync(
        self, target_date: date
    ) -> List[Dict[str, Any]]:
        """Синхронная реализация сбора почасовых данных."""
        hourly_data: List[Dict[str, Any]] = []
        date_pattern = target_date.strftime("%Y-%m-%d")

        for hour in range(24):
            hour_key = f"{date_pattern}_{hour:02d}"
            hour_file = self.hourly_path / f"{hour_key}.json"

            if hour_file.exists():
                try:
                    with open(hour_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        hourly_data.append(data)
                except Exception as e:
                    logger.warning(f"Ошибка чтения почасового файла {hour_file}: {e}")

        return hourly_data

    def _create_daily_summary(
        self, hourly_data: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Создает дневную сводку на основе почасовых данных.

        Почасовые snapshot'ы содержат кумулятивные счётчики (нарастающий итог).
        Дневная сводка вычисляется как разница между последним и первым snapshot'ом.
        Пиковый час определяется по максимальной дельте между соседними часами.
        """
        if not hourly_data:
            return {}

        _COUNTER_KEYS = [
            "requests_total",
            "errors_total",
            "llm_requests_total",
            "tokens_total",
            "registers_extracted",
            "monitoring_page_views",
            "rate_limit_hits",
        ]

        first_summary = hourly_data[0].get("summary", {})
        last_summary = hourly_data[-1].get("summary", {})

        # Дневные итоги = последний snapshot минус первый (дельта за день)
        summary: Dict[str, Any] = {}
        for key in _COUNTER_KEYS:
            summary[key] = last_summary.get(key, 0) - first_summary.get(key, 0)

        summary["peak_hour"] = None
        summary["peak_requests_per_hour"] = 0
        summary["error_rate_percent"] = 0.0

        # Пиковый час — максимальная дельта requests_total между соседними snapshot'ами
        for i in range(1, len(hourly_data)):
            prev = hourly_data[i - 1].get("summary", {})
            curr = hourly_data[i].get("summary", {})
            delta = curr.get("requests_total", 0) - prev.get("requests_total", 0)
            if delta > summary["peak_requests_per_hour"]:
                summary["peak_requests_per_hour"] = delta
                period_key = hourly_data[i].get("period_key", "")
                if "_" in period_key:
                    summary["peak_hour"] = period_key.split("_")[-1]

        # Процент ошибок за день
        if summary["requests_total"] > 0:
            summary["error_rate_percent"] = round(
                (summary["errors_total"] / summary["requests_total"]) * 100, 2
            )

        return summary

    def _create_hourly_breakdown(
        self, hourly_data: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Создает почасовую разбивку для дневного отчета."""
        breakdown = []

        for hour_data in hourly_data:
            hour_summary = hour_data.get("summary", {})
            period_key = hour_data.get("period_key", "")

            # Извлекаем час из period_key
            hour = None
            if "_" in period_key:
                hour = period_key.split("_")[-1]

            breakdown.append(
                {
                    "hour": hour,
                    "period_key": period_key,
                    "timestamp": hour_data.get("timestamp"),
                    "requests": hour_summary.get("requests_total", 0),
                    "errors": hour_summary.get("errors_total", 0),
                    "llm_requests": hour_summary.get("llm_requests_total", 0),
                    "tokens": hour_summary.get("tokens_total", 0),
                }
            )

        # Сортируем по часу для читаемости
        breakdown.sort(key=lambda x: x["hour"] if x["hour"] else "00")

        return breakdown

    async def _cleanup_old_data(self) -> None:
        """Очищает старые данные согласно политикам ротации."""
        try:
            now = datetime.now()

            # Почасовые файлы - удаляем старше 72 часов
            cutoff_hour = now - timedelta(hours=self.retention_limits["hourly"])
            await self._cleanup_files_by_age(self.hourly_path, "hour", cutoff_hour)

            # Дневные файлы - удаляем старше 90 дней
            cutoff_day = now - timedelta(days=self.retention_limits["daily"])
            await self._cleanup_files_by_age(self.daily_path, "day", cutoff_day)

        except Exception as e:
            logger.error(f"Ошибка очистки старых данных: {e}")

    async def _cleanup_files_by_age(
        self, directory: Path, period_type: str, cutoff_date: datetime
    ) -> None:
        """Удаляет файлы старше указанной даты."""
        deleted_count = 0

        for file in directory.glob("*.json"):
            try:
                # Парсим дату из имени файла
                file_date = self._parse_date_from_filename(file.name, period_type)

                if file_date and file_date < cutoff_date:
                    file.unlink()
                    deleted_count += 1

            except Exception as e:
                logger.warning(f"Не удалось обработать файл {file}: {e}")

        if deleted_count > 0:
            logger.debug(f"Удалено {deleted_count} старых {period_type} файлов")

    def _parse_date_from_filename(
        self, filename: str, period_type: str
    ) -> Optional[datetime]:
        """Парсит дату из имени файла."""
        try:
            name_without_ext = filename.replace(".json", "")

            if period_type == "hour":
                # Формат: 2026-04-13_14.json
                return datetime.strptime(name_without_ext, "%Y-%m-%d_%H")
            elif period_type == "day":
                # Формат: 2026-04-13.json
                return datetime.strptime(name_without_ext, "%Y-%m-%d")

        except ValueError:
            pass

        return None

    async def _enforce_size_limits(self) -> None:
        """Контролирует общий размер данных, удаляя самые старые при превышении лимита."""
        try:
            total_size = self._calculate_total_size()

            if total_size <= self.max_total_size:
                return

            total_size_mb = total_size // (1024 * 1024)
            max_size_mb = self.max_total_size // (1024 * 1024)
            logger.info(
                f"Размер данных {total_size_mb}MB превышает лимит {max_size_mb}MB"
            )

            # Собираем все файлы с датами модификации
            all_files = []
            for directory in [
                self.hourly_path,
                self.daily_path,
                self.weekly_path,
                self.monthly_path,
            ]:
                for file in directory.glob("*.json"):
                    try:
                        stat = file.stat()
                        all_files.append((file, stat.st_mtime, stat.st_size))
                    except OSError:
                        pass

            # Сортируем по времени модификации (старые первыми)
            all_files.sort(key=lambda x: x[1])

            # Удаляем старые файлы пока не достигнем лимита
            current_size = total_size
            deleted_count = 0

            for file, mtime, size in all_files:
                if current_size <= self.max_total_size:
                    break

                try:
                    file.unlink()
                    current_size -= size
                    deleted_count += 1
                except OSError as e:
                    logger.warning(f"Не удалось удалить файл {file}: {e}")

            if deleted_count > 0:
                logger.info(
                    f"Удалено {deleted_count} файлов для соблюдения лимита размера"
                )

        except Exception as e:
            logger.error(f"Ошибка контроля размера данных: {e}")

    def _calculate_total_size(self) -> int:
        """Вычисляет общий размер всех агрегированных данных."""
        total_size = 0

        for directory in [
            self.hourly_path,
            self.daily_path,
            self.weekly_path,
            self.monthly_path,
        ]:
            for file in directory.glob("*.json"):
                try:
                    total_size += file.stat().st_size
                except OSError:
                    pass

        return total_size

    def _get_next_hour(self) -> datetime:
        """Возвращает начало следующего часа."""
        now = datetime.now()
        next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        return next_hour

    async def _save_aggregated_data(
        self, file_path: Path, data: Dict[str, Any]
    ) -> None:
        """Сохраняет агрегированные данные в файл."""
        try:
            await asyncio.to_thread(self._save_json_sync, file_path, data)
        except Exception as e:
            logger.error(f"Ошибка сохранения {file_path}: {e}")

    def _save_json_sync(self, file_path: Path, data: Dict[str, Any]) -> None:
        """Синхронная запись JSON в файл."""
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def get_aggregation_status(self) -> Dict[str, Any]:
        """Возвращает статус системы агрегации."""
        total_size = self._calculate_total_size()
        status: Dict[str, Any] = {
            "running": self._aggregation_task is not None
            and not self._aggregation_task.done(),
            "total_size_bytes": total_size,
            "max_size_bytes": self.max_total_size,
            "size_usage_percent": round(
                (total_size / self.max_total_size) * 100, 1
            ),
            "directories": {},
        }

        # Статистика по директориям
        for name, path in [
            ("hourly", self.hourly_path),
            ("daily", self.daily_path),
            ("weekly", self.weekly_path),
            ("monthly", self.monthly_path),
        ]:
            files = list(path.glob("*.json"))
            total_size = sum(f.stat().st_size for f in files if f.exists())

            status["directories"][name] = {
                "files_count": len(files),
                "size_bytes": total_size,
                "retention_limit": self.retention_limits.get(name, "unlimited"),
            }

        return status


# Глобальный экземпляр
_aggregator: Optional[MetricsAggregator] = None


def get_aggregator() -> MetricsAggregator:
    """Возвращает глобальный экземпляр MetricsAggregator."""
    global _aggregator
    if _aggregator is None:
        _aggregator = MetricsAggregator()
    return _aggregator


async def start_metrics_aggregation(
    get_metrics_func: Callable[[], Dict[str, Any]],
) -> None:
    """Запускает автоматическую агрегацию метрик."""
    aggregator = get_aggregator()
    await aggregator.start_aggregation(get_metrics_func)
    logger.info("Система агрегации метрик запущена")


async def stop_metrics_aggregation() -> None:
    """Останавливает автоматическую агрегацию метрик."""
    aggregator = get_aggregator()
    await aggregator.stop_aggregation()
    logger.info("Система агрегации метрик остановлена")
