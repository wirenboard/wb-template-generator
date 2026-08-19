// Проверки и сборка образа для каждой ветки. Кред от хостов у этой джобы нет.
// ВРЕМЕННО для обкатки: библиотека закреплена на ветку с новыми шагами.
// В основной ветке этой строки нет — там берётся master.
@Library('wbci@feature/docker-service-deploy') _

checksDockerService(
    // Первый прогон: без кред реестра и без внешних инструментов — проверяем сам пайплайн.
    runChecks: false,
    pushBranchImages: false,
    imageRepo: 'ghcr.io/wirenboard/wb-template-generator-backend',
    images: [
        [imageRepo: 'ghcr.io/wirenboard/wb-template-generator-backend',  dockerfile: 'backend/Dockerfile',  context: '.'],
        [imageRepo: 'ghcr.io/wirenboard/wb-template-generator-frontend', dockerfile: 'frontend/Dockerfile', context: 'frontend'],
    ],
)
