// ВРЕМЕННО: библиотека закреплена на ветку, снять при слиянии jenkins-pipeline-lib#193.
@Library('wbci@feature/CLOUD-622-docker-service-deploy') _

dockerService(
    checks: ['ci-lint', 'ci-test'],
    images: [
        backend:  [dockerfile: 'backend/Dockerfile'],
        frontend: [dockerfile: 'frontend/Dockerfile', context: 'frontend'],
    ],
)
