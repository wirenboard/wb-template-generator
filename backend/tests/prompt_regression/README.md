# Prompt Regression Tests

Ручные регрессионные тесты для LLM-промпта (`backend/prompts.py`).

При правках промпта LLM может начать неправильно обрабатывать адреса, типы регистров, enum и т.д. Эти тесты помогают выявить регрессии — набор кейсов (маленькие таблички регистров) прогоняется через реальный LLM и проверяется на соответствие ожиданиям.

## Когда запускать

- После любых правок в `backend/prompts.py`
- При смене модели LLM (проверить, что новая модель корректно интерпретирует промпт)
- Перед релизом, если были изменения в промпте

## Как запустить

```bash
docker compose exec backend python tests/prompt_regression/run.py
```

Требует настроенного LLM API — переменные `LLM_API_URL`, `LLM_API_KEY`, `LLM_MODEL` в `.env`.

## Структура

```
tests/prompt_regression/
  run.py               # Скрипт запуска
  expectations.yaml    # Ожидания по каждому кейсу
  README.md            # Этот файл
  cases/
    01_fc_table_coil_discrete.txt   # FC 01/02, адреса как есть
    02_legacy_5digit.txt            # 40001, 30001 → конвертировать
    03_plain_addresses.txt          # Адреса 0, 1, 100 → как есть
    04_bitwise_holding.txt          # Биты в holding → reg:bit:width
    05_coil_switch_no_enum.txt      # Coil/discrete → switch, без enum
```

## Тест-кейсы

| # | Кейс | Что проверяет |
|---|------|---------------|
| 01 | FC table (coil + discrete) | Тип из Function Code, адреса без вычитания |
| 02 | Legacy 5-digit | 40001→holding:0, 30001→input:0 |
| 03 | Plain addresses | Адреса как есть, без вычитания |
| 04 | Bitwise holding | Биты → отдельные регистры `"reg:bit:width"` |
| 05 | Coil/discrete → switch | switch без enum, даже при описанных состояниях 0/1 |

## Формат expectations.yaml

Проверяются только структурные поля — `name`, `description`, `translations` вариативны и не проверяются.

```yaml
case_id:
  registers:
    - address: 1          # int или строка "200:0:1"
      reg_type: coil      # обязательно
      channel_type: switch # опционально
      has_enum: false      # опционально
      format: u16          # опционально
```

## Как добавить новый кейс

1. Создайте файл `cases/NN_description.txt` с мини-таблицей регистров
2. Добавьте ожидания в `expectations.yaml` с ключом `NN_description`
3. Запустите `run.py` и убедитесь, что кейс проходит

## Важно

- Тесты **НЕ входят в CI** — запускаются только вручную
- `run.py` не начинается с `test_` → pytest его не подхватывает
- Результат зависит от конкретной модели LLM — при смене модели возможны изменения
- Exit code: 0 = все PASS, 1 = есть FAIL
