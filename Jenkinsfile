// Проверки и сборка образа для каждой ветки. Кред от хостов у этой джобы нет.
// Джобу заводит организационная папка Jenkins по этому файлу; библиотека wbci
// подключена в ней неявно, объявлять её не нужно.

checksDockerService(
    imageRepo: 'ghcr.io/wirenboard/wb-template-generator-backend',
    images: [
        [imageRepo: 'ghcr.io/wirenboard/wb-template-generator-backend',  dockerfile: 'backend/Dockerfile',  context: '.'],
        [imageRepo: 'ghcr.io/wirenboard/wb-template-generator-frontend', dockerfile: 'frontend/Dockerfile', context: 'frontend'],
    ],
)
