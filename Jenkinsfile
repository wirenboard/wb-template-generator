// Проверки и сборка образа для каждой ветки. Кред от хостов у этой джобы нет.
// Джобу заводит организационная папка Jenkins по этому файлу; библиотека wbci
// подключена в ней неявно, объявлять её не нужно.
//
// ВРЕМЕННО, УБРАТЬ ПЕРЕД СЛИЯНИЕМ: пока шаги живут в ветке jenkins-pipeline-lib#183,
// в master их нет и джоба падает с "No such DSL method". Строка ниже закрепляет
// библиотеку на ту ветку; после слияния #183 её нужно удалить, иначе сервис навсегда
// останется привязан к временной ветке.
@Library('wbci@feature/docker-service-deploy') _

checksDockerService(
    // ВРЕМЕННО, УБРАТЬ ПЕРЕД СЛИЯНИЕМ: кред на push образов продуктовых сервисов
    // инфраструктура ещё не выдала, поэтому образ только собирается.
    pushBranchImages: false,
    // Проверки идут в контейнерах: агент Jenkins общий для всех джоб и инструментов
    // сервиса не несёт. Раньше это же делала джоба GitHub Actions.
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
