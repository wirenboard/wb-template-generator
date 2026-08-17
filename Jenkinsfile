// Джоба выката — привязана к main. Логика в общей библиотеке
// (vars/deployDockerService.groovy, справочник vars/deployDockerService.md);
// здесь только настройки этого сервиса.
//
// Рантайм: Docker Compose на VPS. Тестовой среды нет — окружение одно.
@Library('wb-pipeline-lib') _

deployDockerService(
    deployHost: 'tgen.wirenboard.com',
    imageRepo:  'ghcr.io/wirenboard/wb-template-generator-backend',
    images: [
        [imageRepo: 'ghcr.io/wirenboard/wb-template-generator-backend',  dockerfile: 'backend/Dockerfile',  context: '.'],
        [imageRepo: 'ghcr.io/wirenboard/wb-template-generator-frontend', dockerfile: 'frontend/Dockerfile', context: 'frontend'],
    ],
    // Сервис публикует хостовый порт за nginx хоста: два контейнера один порт не
    // удержат, поэтому пересоздание с кратким миганием, а не rolling.
    composeRolling: false,
    // Сверка после выката: сервис отдаёт git-SHA, из которого собран.
    revisionUrl: 'https://tgen.wirenboard.com/api/status',
)
