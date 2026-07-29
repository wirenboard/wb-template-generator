# ci/

Свои скрипты — только там, где готового GitHub Action нет. Всё остальное в конвейере
делают действия: сборка и пуш образов — `docker/build-push-action`, доставка и команды
на сервере — `appleboy/scp-action` + `appleboy/ssh-action` (вызываются из локального
composite-действия `.github/actions/deploy`), журнал выкатов — `bobheadxi/deployments`,
проверка CHANGELOG в PR — `dangoslen/changelog-enforcer`.

| Скрипт | Зачем свой |
|---|---|
| `shell/smoke.sh` | сверяет `revision` из `/api/status` с выкаченным SHA — контракт нашего сервиса |
| `shell/guard_staleness.sh` | сравнение с `origin/main` перед выкатом |
| `shell/conformance.sh` | проверка репозитория на соответствие гейту стандарта (`make conformance`) |

## last-good и журнал

Источник правды о выкатах — **журнал GitHub Deployments**: последний `success` = то, что
в проде; на него же опирается откат. Файл `last-good-sha` (+ `.prev`) на сервере — только
break-glass-зеркало на случай недоступного GitHub; пишется после успешного smoke.

## Секреты и переменные (среда `production`)

`DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`, `DEPLOY_DIR`, `PROD_URL` — секреты;
`DEPLOY_HOST_FINGERPRINT` — variable (SHA256-отпечаток хоста).

Секреты только из окружения. Скрипты проверяются `make lint-shell` (shellcheck + `bash -n`)
в составе `make lint`. Юнит-тестов на выкат нет: он проверяется боевым прогоном и smoke.
