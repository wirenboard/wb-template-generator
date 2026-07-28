# ci/ — логика конвейера

Правило стандарта деплоя: в YAML нет shell-команд выката. Вся нетривиальная логика — здесь,
вызывается через `make`, который зовёт эти скрипты. Тонкий workflow только задаёт
структуру (триггеры, входы, секреты) и вызывает `make <цель>`.

| Скрипт | Что делает | Кем вызывается |
|---|---|---|
| `shell/guard_staleness.sh` | сторож свежести ветки: стоп, если отстала от `origin/main` | `make guard-staleness` |
| `shell/deploy.sh` | выкат неизменяемого образа по git-SHA: compose из git @ TAG → pull → rolling-update → verify | `make deploy` |
| `shell/rollback.sh` | откат на прошлый хороший SHA (тот же путь, что deploy) | `make rollback` |
| `shell/smoke.sh` | проверка живости после выката с ретраями (+ сверка `revision`) | `make smoke` |
| `shell/last_good.sh` | чтение/запись break-glass-зеркала `last-good-sha` на сервере | шаги `push_master` |
| `shell/conformance.sh` | проверка репозитория на соответствие prod-ready гейту (🔒 hard / 👁 monitor) | `make conformance` |

## Как устроен last-good (двухфазно)

Источник правды о выкатах — **журнал GitHub Deployments**: последний `success` = то, что
сейчас в проде. Файл `last-good-sha` на сервере — только **break-glass-зеркало** для случая
«GitHub недоступен, откатываться надо руками».

- `deploy.sh` **не пишет** last-good: контейнер стал healthy — это ещё не «хорошая версия»,
  впереди smoke.
- Пишет отдельный шаг `push_master` **после успешного smoke**, через `last_good.sh write`.
- Хранятся два значения: `last-good-sha` (current) и `last-good-sha.prev`. Одного мало —
  сбой, проявившийся спустя часы после зелёного smoke, оставил бы в файле саму плохую версию.

## Требуемое окружение (секреты/переменные)

- `DEPLOY_HOST` — `user@host` боевого сервера
- `DEPLOY_DIR` — каталог со стеком на сервере (по умолчанию `/srv/wb-template-generator`)
- `PROD_URL` — базовый адрес для smoke
- `DEPLOY_KNOWN_HOSTS` — отпечаток сервера (repo variable, не секрет)
- `REGISTRY` — префикс реестра (по умолчанию `ghcr.io/wirenboard`)
- SSH-ключ в ssh-agent (jump-host — через `~/.ssh/config`)

## Правила

- Секреты только из окружения, никогда не в коде/логах.
- Скрипты проверяются наравне с кодом приложения: `make lint-shell` (shellcheck + `bash -n`)
  входит в `make lint` и гоняется в CI.
- Юнит-тестов на сами выкаты нет и не будет без интеграционного стенда: они SSH-ят на боевой
  сервер и запускают docker. Что можно проверять статикой — проверяется линтом; поведение
  проверяется на боевом прогоне и failure-injection (см. `DEPLOYING.md`).
