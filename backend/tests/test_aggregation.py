"""Тесты для модуля aggregation."""

import json
import shutil
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.append("..")

from aggregation import MetricsAggregator


@pytest.fixture
def temp_dir():
    """Создает временную директорию для тестов."""
    temp_path = Path(tempfile.mkdtemp())
    yield temp_path
    shutil.rmtree(temp_path, ignore_errors=True)


@pytest.fixture
def aggregator(temp_dir):
    """Создает экземпляр MetricsAggregator для тестов."""
    return MetricsAggregator(base_path=str(temp_dir))


@pytest.fixture
def sample_metrics():
    """Возвращает образец метрик для тестов."""
    return {
        "basic": {
            "counters": {
                "analyze_requests": 10,
                "analyze_errors": 2,
                "monitoring_page_views": 5,
                "rate_limit_hits": 1,
            }
        },
        "llm": {
            "counters": {"llm_requests": 8},
            "tokens": {"total_tokens": 5000},
            "processing": {"registers_extracted": 25},
        },
    }


class TestMetricsAggregator:
    """Тесты для класса MetricsAggregator."""

    def test_init_creates_directories(self, aggregator, temp_dir):
        """Тест создания директорий при инициализации."""
        assert (temp_dir / "hourly").exists()
        assert (temp_dir / "daily").exists()
        assert (temp_dir / "weekly").exists()
        assert (temp_dir / "monthly").exists()

    def test_retention_limits(self, aggregator):
        """Тест корректности лимитов ретенции."""
        assert aggregator.retention_limits["hourly"] == 72
        assert aggregator.retention_limits["daily"] == 90
        assert aggregator.retention_limits["weekly"] == 52
        assert aggregator.retention_limits["monthly"] == 999999

    def test_create_hourly_summary(self, aggregator, sample_metrics):
        """Тест создания почасовой сводки."""
        summary = aggregator._create_hourly_summary(sample_metrics)

        assert summary["requests_total"] == 10
        assert summary["errors_total"] == 2
        assert summary["llm_requests_total"] == 8
        assert summary["tokens_total"] == 5000
        assert summary["registers_extracted"] == 25
        assert summary["monitoring_page_views"] == 5
        assert summary["rate_limit_hits"] == 1

    @pytest.mark.asyncio
    async def test_perform_hourly_aggregation(
        self, aggregator, sample_metrics, temp_dir
    ):
        """Тест выполнения почасовой агрегации."""

        # Мокаем функцию получения метрик
        def get_metrics_func():
            return sample_metrics

        await aggregator._perform_hourly_aggregation(get_metrics_func)

        # Проверяем, что файл создался
        now = datetime.now()
        hour_key = now.strftime("%Y-%m-%d_%H")
        hour_file = temp_dir / "hourly" / f"{hour_key}.json"

        assert hour_file.exists()

        # Проверяем содержимое
        with open(hour_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert data["period"] == "hour"
        assert data["period_key"] == hour_key
        assert "timestamp" in data
        assert "summary" in data
        assert data["summary"]["requests_total"] == 10

    def test_parse_date_from_filename(self, aggregator):
        """Тест парсинга дат из имен файлов."""
        # Тест почасового формата
        hour_date = aggregator._parse_date_from_filename("2026-04-13_14.json", "hour")
        expected_hour = datetime(2026, 4, 13, 14)
        assert hour_date == expected_hour

        # Тест дневного формата
        day_date = aggregator._parse_date_from_filename("2026-04-13.json", "day")
        expected_day = datetime(2026, 4, 13)
        assert day_date == expected_day

        # Тест некорректного формата
        invalid_date = aggregator._parse_date_from_filename("invalid.json", "hour")
        assert invalid_date is None

    def test_calculate_total_size(self, aggregator, temp_dir):
        """Тест вычисления общего размера данных."""
        # Создаем несколько тестовых файлов
        test_files = [
            temp_dir / "hourly" / "2026-04-13_10.json",
            temp_dir / "daily" / "2026-04-13.json",
        ]

        for file_path in test_files:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump({"test": "data"}, f)

        total_size = aggregator._calculate_total_size()
        assert total_size > 0

        # Проверяем, что размер равен сумме размеров файлов
        expected_size = sum(f.stat().st_size for f in test_files)
        assert total_size == expected_size

    @pytest.mark.asyncio
    async def test_cleanup_files_by_age(self, aggregator, temp_dir):
        """Тест очистки старых файлов."""
        hourly_dir = temp_dir / "hourly"

        # Создаем файлы с разными датами
        old_file = hourly_dir / "2026-04-10_10.json"
        recent_file = hourly_dir / "2026-04-13_10.json"

        for file_path in [old_file, recent_file]:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump({"test": "data"}, f)

        # Задаем границу - файлы старше 12 апреля удаляются
        cutoff_date = datetime(2026, 4, 12)

        await aggregator._cleanup_files_by_age(hourly_dir, "hour", cutoff_date)

        # Старый файл должен быть удален, новый - остаться
        assert not old_file.exists()
        assert recent_file.exists()

    def test_create_daily_summary(self, aggregator):
        """Тест создания дневной сводки."""
        # Создаем тестовые почасовые данные
        hourly_data = []
        for hour in range(0, 24, 4):  # Каждые 4 часа
            hour_data = {
                "period_key": f"2026-04-13_{hour:02d}",
                "timestamp": f"2026-04-13T{hour:02d}:00:00",
                "summary": {
                    "requests_total": hour + 5,
                    "errors_total": hour // 12,  # Ошибки только в поздние часы
                    "llm_requests_total": hour,
                    "tokens_total": (hour + 1) * 1000,
                    "registers_extracted": hour * 10,
                    "monitoring_page_views": hour + 2,
                    "rate_limit_hits": 0,
                },
            }
            hourly_data.append(hour_data)

        summary = aggregator._create_daily_summary(hourly_data)

        # Проверяем агрегированные значения
        expected_requests = sum(h["summary"]["requests_total"] for h in hourly_data)
        expected_errors = sum(h["summary"]["errors_total"] for h in hourly_data)

        assert summary["requests_total"] == expected_requests
        assert summary["errors_total"] == expected_errors
        assert summary["peak_hour"] == "20"  # Максимум в 20:00
        assert summary["error_rate_percent"] == round(
            (expected_errors / expected_requests) * 100, 2
        )

    def test_create_hourly_breakdown(self, aggregator):
        """Тест создания почасовой разбивки."""
        hourly_data = [
            {
                "period_key": "2026-04-13_10",
                "timestamp": "2026-04-13T10:00:00",
                "summary": {
                    "requests_total": 15,
                    "errors_total": 1,
                    "llm_requests_total": 10,
                    "tokens_total": 5000,
                },
            },
            {
                "period_key": "2026-04-13_14",
                "timestamp": "2026-04-13T14:00:00",
                "summary": {
                    "requests_total": 25,
                    "errors_total": 0,
                    "llm_requests_total": 20,
                    "tokens_total": 8000,
                },
            },
        ]

        breakdown = aggregator._create_hourly_breakdown(hourly_data)

        assert len(breakdown) == 2
        assert breakdown[0]["hour"] == "10"
        assert breakdown[0]["requests"] == 15
        assert breakdown[1]["hour"] == "14"
        assert breakdown[1]["requests"] == 25

    @pytest.mark.asyncio
    async def test_collect_hourly_data_for_day(self, aggregator, temp_dir):
        """Тест сбора почасовых данных за день."""
        target_date = date(2026, 4, 13)
        hourly_dir = temp_dir / "hourly"

        # Создаем файлы за целевую дату
        test_hours = [10, 14, 18]
        for hour in test_hours:
            hour_file = hourly_dir / f"2026-04-13_{hour:02d}.json"
            test_data = {
                "period_key": f"2026-04-13_{hour:02d}",
                "summary": {"requests_total": hour},
            }
            with open(hour_file, "w", encoding="utf-8") as f:
                json.dump(test_data, f)

        # Создаем файл за другую дату (не должен попасть в результат)
        other_file = hourly_dir / "2026-04-12_10.json"
        with open(other_file, "w", encoding="utf-8") as f:
            json.dump({"test": "other_day"}, f)

        data = await aggregator._collect_hourly_data_for_day(target_date)

        assert len(data) == 3
        # Проверяем, что все данные относятся к целевой дате
        for item in data:
            assert item["period_key"].startswith("2026-04-13_")

    @pytest.mark.asyncio
    async def test_perform_daily_aggregation_if_needed(self, aggregator, temp_dir):
        """Тест условного выполнения дневной агрегации."""
        # Тест 1: не в 00:00 - агрегация не должна запуститься
        with patch("aggregation.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2026, 4, 13, 15, 30)  # 15:30
            mock_datetime.date.side_effect = lambda *args, **kwargs: date(
                *args, **kwargs
            )

            await aggregator._perform_daily_aggregation_if_needed()

            # Файлы дневной агрегации не должны создаться
            daily_files = list((temp_dir / "daily").glob("*.json"))
            assert len(daily_files) == 0

        # Тест 2: в 00:00 но без почасовых данных
        with patch("aggregation.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2026, 4, 13, 0, 5)  # 00:05
            mock_datetime.date.side_effect = lambda *args, **kwargs: date(
                *args, **kwargs
            )

            await aggregator._perform_daily_aggregation_if_needed()

            daily_files = list((temp_dir / "daily").glob("*.json"))
            assert len(daily_files) == 0

    def test_get_aggregation_status(self, aggregator, temp_dir):
        """Тест получения статуса агрегации."""
        # Создаем несколько файлов
        hourly_file = temp_dir / "hourly" / "2026-04-13_10.json"
        daily_file = temp_dir / "daily" / "2026-04-13.json"

        for file_path in [hourly_file, daily_file]:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump({"test": "data"}, f)

        status = aggregator.get_aggregation_status()

        assert "running" in status
        assert "total_size_bytes" in status
        assert "max_size_bytes" in status
        assert "size_usage_percent" in status
        assert "directories" in status

        # Проверяем статистику по директориям
        assert status["directories"]["hourly"]["files_count"] == 1
        assert status["directories"]["daily"]["files_count"] == 1
        assert status["directories"]["hourly"]["retention_limit"] == 72
        assert status["directories"]["daily"]["retention_limit"] == 90

    @pytest.mark.asyncio
    async def test_enforce_size_limits(self, aggregator, temp_dir):
        """Тест принудительного соблюдения лимитов размера."""
        # Устанавливаем очень маленький лимит
        aggregator.max_total_size = 100  # 100 байт

        # Создаем файлы, которые превышают лимит
        large_data = {"data": "x" * 200}  # Большие данные

        files = [
            temp_dir / "hourly" / "2026-04-10_10.json",
            temp_dir / "hourly" / "2026-04-13_10.json",
            temp_dir / "daily" / "2026-04-12.json",
        ]

        for file_path in files:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(large_data, f)

        # Проверяем, что размер превышает лимит
        initial_size = aggregator._calculate_total_size()
        assert initial_size > aggregator.max_total_size

        # Применяем лимиты
        await aggregator._enforce_size_limits()

        # Проверяем, что размер уменьшился (некоторые файлы удалились)
        final_size = aggregator._calculate_total_size()
        assert final_size < initial_size

    @pytest.mark.asyncio
    async def test_start_stop_aggregation(self, aggregator):
        """Тест запуска и остановки агрегации."""
        # Мокаем get_metrics_func
        get_metrics_func = AsyncMock(return_value={})

        # Запускаем агрегацию
        await aggregator.start_aggregation(get_metrics_func)
        assert aggregator._aggregation_task is not None
        assert not aggregator._aggregation_task.done()

        # Останавливаем агрегацию
        await aggregator.stop_aggregation()
        assert aggregator._aggregation_task is None

    def test_get_next_hour(self, aggregator):
        """Тест расчета следующего часа."""
        # Тестируем для конкретного времени
        with patch("aggregation.datetime") as mock_datetime:
            test_time = datetime(2026, 4, 13, 14, 30, 45)  # 14:30:45
            mock_datetime.now.return_value = test_time

            next_hour = aggregator._get_next_hour()
            expected = datetime(2026, 4, 13, 15, 0, 0)  # 15:00:00
            assert next_hour == expected
