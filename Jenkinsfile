// ВРЕМЕННО: финальная обкатка серии jenkins-pipeline-lib #191 + #196 + #193.
// Релиз уходит в джобу-пустышку, ревизия проверяется по GitHub API, хосты не трогаются.
@Library('wbci@feature/CLOUD-622-docker-service-deploy') _

dockerService(
    checks: ['ci-lint', 'ci-test'],
    images: [backend: [repository: 'ghcr.io/wirenboard/wb-tgen-smoke',
                       dockerfile: 'backend/Dockerfile']],
)
