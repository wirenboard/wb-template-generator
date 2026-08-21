// Проверки и сборка образа для каждой ветки. Кред от хостов у этой джобы нет.
// ВРЕМЕННО для обкатки: библиотека закреплена на ветку с новыми шагами.
// В основной ветке этой строки нет — там берётся master.
@Library('wbci@feature/docker-service-deploy') _

checksDockerService(
    // Обкатка: push образов выключен — кред реестра для продуктовых сервисов пока нет.
    runChecks: true,
    pushBranchImages: true,
    // Проверки идут в контейнерах, как раньше в GitHub Actions: агент Jenkins общий
    // и инструментов сервиса не несёт.
    checkEnvironments: [
        [image:   'python:3.12-slim',
         prepare: 'apt-get update && apt-get install -y --no-install-recommends make poppler-utils curl && pip install --no-cache-dir -r backend/requirements.txt',
         targets: ['lint-backend', 'test-backend']],
        [image:   'node:20-alpine',
         prepare: 'apk add --no-cache make && cd frontend && npm ci',
         targets: ['lint-frontend', 'test-frontend']],
    ],
    imageRepo: 'ghcr.io/wirenboard/wb-template-generator-backend',
    images: [
        [imageRepo: 'ghcr.io/wirenboard/wb-template-generator-backend',  dockerfile: 'backend/Dockerfile',  context: '.'],
        [imageRepo: 'ghcr.io/wirenboard/wb-template-generator-frontend', dockerfile: 'frontend/Dockerfile', context: 'frontend'],
    ],
)
