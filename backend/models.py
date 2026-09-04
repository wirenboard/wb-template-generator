"""Pydantic-модели данных для API запросов и ответов."""

from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, StringConstraints, model_validator

# Потолки на длину строк и размер списков ограничивают объём работы одного запроса.
# Детекция паттернов в jinja_exporter копирует строку на каждое число в ней, поэтому
# расход растёт и по длине строки, и по числу каналов.
ShortText = Annotated[str, StringConstraints(max_length=512)]
LongText = Annotated[str, StringConstraints(max_length=2048)]
# Запись `definitions/serial_int` — число и hex-строка равноправны
SerialInt = int | ShortText
MAX_REGISTERS = 5_000
MAX_GROUPS = 2_000
MAX_ENUM_ENTRIES = 4_096
# Строк в одном запросе на перевод. Перевод уходит на серверный ключ, поэтому потолок конечный.
MAX_TRANSLATE_STRINGS = 10_000


class DeviceInfo(BaseModel):
    """Информация об устройстве — имя, идентификатор, группа."""

    name: ShortText = ""
    id: ShortText = ""
    device_group: ShortText | None = None
    # Поля, сохраняемые при roundtrip импорт→экспорт
    hw: list[dict] | None = None
    max_read_registers: int | None = None
    response_timeout_ms: int | None = None
    frame_timeout_ms: int | None = None
    enable_wb_continuous_read: bool | None = None
    title_key: ShortText | None = None
    title_translations: dict[str, ShortText] | None = None


class EnumEntry(BaseModel):
    """Элемент enum с переводами на произвольные языки."""

    value: int
    title: ShortText = ""
    translations: dict[str, ShortText] | None = None

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

    title: ShortText | None = None
    description: LongText | None = None


class RegisterGroup(BaseModel):
    """Группа регистров с переводами."""

    id: ShortText
    title: ShortText = ""
    order: int = 0
    description: LongText | None = None
    translations: dict[str, GroupTranslation] | None = None
    parent_group: ShortText | None = None
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

    name: ShortText | None = None
    description: LongText | None = None


class Register(BaseModel):
    """Описание одного Modbus-регистра устройства."""

    id: ShortText = Field(default_factory=lambda: str(uuid4()))
    # int или строка "109:1:2" для побитового доступа
    address: int | Annotated[str, StringConstraints(max_length=64)]
    name: ShortText
    reg_type: ShortText = "holding"
    format: ShortText = "u16"
    scale: float = 1
    offset: float = 0
    units: ShortText | None = None
    access: Literal["read", "write", "readwrite"] = "read"
    description: LongText | None = None
    channel_type: ShortText = "value"
    group: ShortText = "general"
    group_title: ShortText | None = None
    is_parameter: bool = False

    condition: LongText | None = None
    enabled: bool = True
    enum: list[int] | None = Field(default=None, max_length=MAX_ENUM_ENTRIES)
    enum_titles: list[ShortText] | None = Field(default=None, max_length=MAX_ENUM_ENTRIES)
    enum_entries: list[EnumEntry] | None = Field(default=None, max_length=MAX_ENUM_ENTRIES)
    string_data_size: int | None = None
    word_order: ShortText | None = None
    byte_order: ShortText | None = None
    error_value: SerialInt | None = None
    readonly: bool | None = None
    min: int | float | None = None
    max: int | float | None = None
    round_to: int | float | None = None
    on_value: SerialInt | None = None
    off_value: SerialInt | None = None
    default_value: int | float | None = None
    translations: dict[str, RegisterTranslation] | None = None
    group_title_translations: dict[str, ShortText] | None = None
    # Поля для roundtrip
    sporadic: bool | None = None
    read_only: bool | None = None
    required: bool | None = None
    fw: ShortText | None = None
    original_channel_id: ShortText | None = None
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
    registers: list[Register] = Field(max_length=MAX_REGISTERS)


class AnalyzeResponse(DeviceData):
    """Ответ эндпоинта /api/analyze — информация об устройстве и список регистров."""

    pass


class BuildRequest(DeviceData):
    """Запрос на сборку JSON-шаблона из отредактированных пользователем данных."""

    groups: list[RegisterGroup] = Field(default=[], max_length=MAX_GROUPS)


class ValidateRequest(BaseModel):
    """Запрос на валидацию списка регистров."""

    registers: list[Register] = Field(max_length=MAX_REGISTERS)


class LlmOverrides(BaseModel):
    """Настройки LLM, которые клиент присылает в теле запроса.

    Именно в теле, а не аргументами эндпоинта — FastAPI разбирал бы их как
    query-параметры, и ключ попадал бы в access-логи nginx и uvicorn. Что с чем
    сравнивается дальше, решает `resolve_llm_target` в llm_service.
    """

    llm_api_url: ShortText | None = None
    llm_api_key: ShortText | None = None
    llm_model: ShortText | None = None
    llm_timeout: int | None = None
    llm_legacy_max_tokens: bool | None = None
    # Верхняя граница у провайдеров разная, 2 — потолок OpenAI-совместимых
    llm_temperature: Annotated[float, Field(ge=0, le=2)] | None = None


class FixRegistersRequest(ValidateRequest, LlmOverrides):
    """Запрос на исправление регистров через LLM."""


class TranslateRequest(LlmOverrides):
    """Запрос на перевод строк через LLM."""

    # key → English text
    strings: dict[ShortText, LongText] = Field(max_length=MAX_TRANSLATE_STRINGS)
    target_lang: ShortText  # "ru", "de" и т.д.
    target_lang_name: ShortText  # "Russian", "Deutsch" — для промпта


class TranslateResponse(BaseModel):
    """Ответ перевода строк."""

    translations: dict[str, str]  # key → translated text
