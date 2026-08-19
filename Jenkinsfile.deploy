// Выкат. Логика — в общей библиотеке, справочник vars/deployDockerService.md.
@Library('wb-pipeline-lib') _

deployDockerService(
    deployHost: 'tgen.wirenboard.com',
    imageRepo:  'ghcr.io/wirenboard/wb-template-generator-backend',
    images: [
        [imageRepo: 'ghcr.io/wirenboard/wb-template-generator-backend',  dockerfile: 'backend/Dockerfile',  context: '.'],
        [imageRepo: 'ghcr.io/wirenboard/wb-template-generator-frontend', dockerfile: 'frontend/Dockerfile', context: 'frontend'],
    ],
    // Сервис держит хостовый порт — два контейнера его не поделят, значит пересоздание.
    composeRolling: false,
    revisionUrl: 'https://tgen.wirenboard.com/api/status',
)
