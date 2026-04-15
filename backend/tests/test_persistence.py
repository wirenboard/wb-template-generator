"""Тесты для модуля persistence."""

import json
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.append("..")

from persistence import MetricsPersistence


@pytest.fixture
def temp_dir():
    """Создает временную директорию для тестов."""
    temp_path = Path(tempfile.mkdtemp())
    yield temp_path
    shutil.rmtree(temp_path, ignore_errors=True)


@pytest.fixture
def persistence(temp_dir):
    """Создает экземпляр MetricsPersistence для тестов."""
    return MetricsPersistence(base_path=str(temp_dir))


class TestMetricsPersistence:
    """Тесты для класса MetricsPersistence."""

    def test_init_creates_directories(self, persistence, temp_dir):
        """Тест создания директорий при инициализации."""
        assert (temp_dir / "current").exists()
        assert (
            persistence.basic_metrics_file
            == temp_dir / "current" / "basic_metrics.json"
        )
        assert persistence.llm_metrics_file == temp_dir / "current" / "llm_metrics.json"

    @pytest.mark.asyncio
    async def test_save_metrics_basic(self, persistence, temp_dir):
        """Тест сохранения базовых метрик."""
        test_data = {
            "basic": {"counters": {"analyze_requests": 10, "analyze_errors": 2}}
        }

        result = await persistence.save_metrics(test_data)
        assert result is True

        # Проверяем, что файл создался
        basic_file = temp_dir / "current" / "basic_metrics.json"
        assert basic_file.exists()

        # Проверяем содержимое
        with open(basic_file, "r", encoding="utf-8") as f:
            saved_data = json.load(f)

        assert "timestamp" in saved_data
        assert saved_data["data"] == test_data["basic"]

    @pytest.mark.asyncio
    async def test_save_metrics_llm(self, persistence, temp_dir):
        """Тест сохранения LLM метрик."""
        test_data = {"llm": {"counters": {"llm_requests": 5, "llm_errors": 1}}}

        result = await persistence.save_metrics(test_data)
        assert result is True

        # Проверяем файл
        llm_file = temp_dir / "current" / "llm_metrics.json"
        assert llm_file.exists()

        with open(llm_file, "r", encoding="utf-8") as f:
            saved_data = json.load(f)

        assert saved_data["data"] == test_data["llm"]

    @pytest.mark.asyncio
    async def test_load_metrics_no_files(self, persistence):
        """Тест загрузки данных когда файлов нет."""
        result = await persistence.load_metrics()
        assert result == {}

    @pytest.mark.asyncio
    async def test_load_metrics_with_files(self, persistence, temp_dir):
        """Тест загрузки существующих данных."""
        # Создаем тестовые данные
        test_data = {
            "basic": {"counters": {"analyze_requests": 5}},
            "llm": {"counters": {"llm_requests": 3}},
        }

        # Сохраняем данные
        await persistence.save_metrics(test_data)

        # Загружаем данные
        loaded_data = await persistence.load_metrics()

        assert loaded_data["basic"] == test_data["basic"]
        assert loaded_data["llm"] == test_data["llm"]
        assert "basic_timestamp" in loaded_data
        assert "llm_timestamp" in loaded_data

    @pytest.mark.asyncio
    async def test_atomic_write(self, persistence, temp_dir):
        """Тест атомарной записи."""
        test_data = {"basic": {"test": "value"}}

        result = await persistence.save_metrics(test_data)
        assert result is True

        # Проверяем, что основной файл существует
        basic_file = temp_dir / "current" / "basic_metrics.json"
        assert basic_file.exists()

        # Проверяем, что временных файлов нет
        temp_files = list(temp_dir.rglob("*.tmp"))
        assert len(temp_files) == 0

    @pytest.mark.asyncio
    async def test_start_auto_save(self, persistence):
        """Тест запуска автосохранения."""
        # Создаем мок функции получения метрик
        test_metrics = {"basic": {"test": "data"}}

        def mock_get_metrics():
            return test_metrics

        await persistence.start_auto_save(mock_get_metrics)

        assert persistence._auto_save_task is not None
        assert not persistence._auto_save_task.done()

        # Останавливаем
        await persistence.stop_auto_save()

    @pytest.mark.asyncio
    async def test_stop_auto_save(self, persistence):
        """Тест остановки автосохранения."""

        # Создаем мок функции
        def mock_get_metrics():
            return {}

        # Запускаем автосохранение
        await persistence.start_auto_save(mock_get_metrics)

        # Останавливаем
        await persistence.stop_auto_save()

        assert persistence._auto_save_task is None

    @pytest.mark.asyncio
    async def test_save_error_handling(self, persistence):
        """Тест обработки ошибок при сохранении."""
        # Используем некорректные данные
        test_data = {"basic": object()}  # object() не сериализуется в JSON

        result = await persistence.save_metrics(test_data)
        assert result is False

    @pytest.mark.asyncio
    async def test_load_json_file_not_exists(self, persistence):
        """Тест загрузки несуществующего файла."""
        non_existent = Path("/tmp/non_existent.json")
        result = await persistence._load_json(non_existent)
        assert result is None

    @pytest.mark.asyncio
    async def test_save_json_atomic_creates_temp_file(self, persistence, temp_dir):
        """Тест создания временного файла при атомарной записи."""
        target_file = temp_dir / "test.json"
        test_data = {"key": "value"}

        await persistence._save_json_atomic(target_file, test_data)

        # Проверяем, что целевой файл создался
        assert target_file.exists()

        # Проверяем содержимое
        with open(target_file, "r", encoding="utf-8") as f:
            loaded_data = json.load(f)
        assert loaded_data == test_data
