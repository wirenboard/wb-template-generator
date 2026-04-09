"""Pydantic-модели данных для API запросов и ответов."""

from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


class DeviceInfo(BaseModel):
    """Информация об устройстве — имя, идентификатор, группа."""

    name: str = ""
    id: str = ""
    device_group: str | None = None
    # Поля, сохраняемые при roundtrip импорт→экспорт
    hw: list[dict] | None = None
    max_read_registers: int | None = None
    response_timeout_ms: int | None = None
    frame_timeout_ms: int | None = None
    enable_wb_continuous_read: bool | None = None
    title_key: str | None = None
    title_translations: dict[str, str] | None = None


class EnumEntry(BaseModel):
    """Элемент enum с переводами на произвольные языки."""

    value: int
    title: str = ""
    translations: dict[str, str] | None = None

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy(cls, data: dict) -> dict:
        """Обратная совместимость: title_en/title_ru → title + translations."""
        if not isinstance(data, dict):
            return data
        if "title_en" in data and "title" not in data:
            data["title"] = data.pop("title_en")
        else:
            data.pop("title_en", None)
        title_ru = data.pop("title_ru", None)
        if title_ru and "translations" not in data:
            data["translations"] = {"ru": title_ru}
        return data


class GroupTranslation(BaseModel):
    """Переводы для группы: title и description."""

    title: str | None = None
    description: str | None = None


class RegisterGroup(BaseModel):
    """Группа регистров с переводами."""

    id: str
    title: str = ""
    order: int = 0
    description: str | None = None
    translations: dict[str, GroupTranslation] | None = None
    parent_group: str | None = None
    ui_options: dict | None = None

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy(cls, data: dict) -> dict:
        """Обратная совместимость: title_en/title_ru → title + translations."""
        if not isinstance(data, dict):
            return data
        if "title_en" in data and "title" not in data:
            data["title"] = data.pop("title_en")
        else:
            data.pop("title_en", None)
        title_ru = data.pop("title_ru", None)
        if title_ru and "translations" not in data:
            data["translations"] = {"ru": {"title": title_ru}}
        return data


class RegisterTranslation(BaseModel):
    """Переводы для регистра: name и description."""

    name: str | None = None
    description: str | None = None


class Register(BaseModel):
    """Описание одного Modbus-регистра устройства."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    address: int | str  # int или строка "109:1:2" для побитового доступа
    name: str
    reg_type: str = "holding"
    format: str = "u16"
    scale: float = 1
    offset: float = 0
    units: str | None = None
    access: Literal["read", "write", "readwrite"] = "read"
    description: str | None = None
    channel_type: str = "value"
    group: str = "general"
    group_title: str | None = None
    is_parameter: bool = False

    condition: str | None = None
    enabled: bool = True
    enum: list[int] | None = None
    enum_titles: list[str] | None = None
    enum_entries: list[EnumEntry] | None = None
    string_data_size: int | None = None
    word_order: str | None = None
    byte_order: str | None = None
    error_value: str | None = None
    readonly: bool | None = None
    min: int | float | None = None
    max: int | float | None = None
    round_to: int | float | None = None
    on_value: int | None = None
    off_value: int | None = None
    default_value: int | float | None = None
    translations: dict[str, RegisterTranslation] | None = None
    group_title_translations: dict[str, str] | None = None
    # Поля для roundtrip
    sporadic: bool | None = None
    read_only: bool | None = None
    required: bool | None = None
    fw: str | None = None
    original_channel_id: str | None = None
    param_order: int | None = None

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy(cls, data: dict) -> dict:
        """Обратная совместимость: name_ru/description_ru/group_title_ru → translations."""
        if not isinstance(data, dict):
            return data
        name_ru = data.pop("name_ru", None)
        description_ru = data.pop("description_ru", None)
        data.pop("group_title_ru", None)
        if (name_ru or description_ru) and "translations" not in data:
            ru: dict[str, str] = {}
            if name_ru:
                ru["name"] = name_ru
            if description_ru:
                ru["description"] = description_ru
            data["translations"] = {"ru": ru}
        return data


class DeviceData(BaseModel):
    """Базовый класс — информация об устройстве и список регистров."""

    device_info: DeviceInfo
    registers: list[Register]


class AnalyzeResponse(DeviceData):
    """Ответ эндпоинта /api/analyze — информация об устройстве и список регистров."""

    pass


class BuildRequest(DeviceData):
    """Запрос на сборку JSON-шаблона из отредактированных пользователем данных."""

    groups: list[RegisterGroup] = []


class ValidateRequest(BaseModel):
    """Запрос на валидацию списка регистров."""

    registers: list[Register]


class TranslateRequest(BaseModel):
    """Запрос на перевод строк через LLM."""

    strings: dict[str, str]  # key → English text
    target_lang: str  # "ru", "de" и т.д.
    target_lang_name: str  # "Russian", "Deutsch" — для промпта
    llm_api_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    llm_temperature: float | None = None
    llm_timeout: int | None = None
    llm_legacy_max_tokens: bool | None = None


class TranslateResponse(BaseModel):
    """Ответ перевода строк."""

    translations: dict[str, str]  # key → translated text
